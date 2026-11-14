import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.export_catalog_metadata import export, metadata_rows


def item():
    return {
        "entity_key": "article:a",
        "kind": "article",
        "source_id": "a",
        "source_table": "Articles",
        "title": "Тест",
        "description": "",
        "topics": ["Управление"],
        "tags": [],
        "industries": [],
        "provenance": {"title": "Articles.Title", "description": "Articles.Description"},
        "data_quality_flags": ["url_unverified"],
    }


def report():
    return {
        "generation": "test-generation",
        "catalog_sha256": "test-catalog-hash",
        "eligible_items": 1,
        "duplicate_entity_keys": 0,
        "title_description_mapping": {},
        "facet_mapping": {field: {} for field in ("topics", "tags", "industries")},
        "missing_by_field": {"description": 1},
    }


class CatalogMetadataExportTests(unittest.TestCase):
    def test_rows_preserve_unknowns_and_source_without_user_content(self):
        source = {**item(), "body": "private body", "user_id": "private user"}
        row = metadata_rows([source])[0]
        self.assertEqual(row["topics"], ["Управление"])
        self.assertEqual(row["provenance"]["topics"], "ContentSettingsTopics -> Topics.Title")
        self.assertIsNone(row["provenance"]["description"])
        self.assertIsNone(row["provenance"]["industries"])
        self.assertNotIn("body", row)
        self.assertNotIn("user_id", row)

    def test_rejects_invalid_identity_duplicates_and_wrong_provenance(self):
        for catalog in (
            [item(), item()],
            [{**item(), "entity_key": "article:other"}],
            [{**item(), "provenance": {"title": "fake", "description": "Articles.Description"}}],
        ):
            with self.subTest(catalog=catalog), self.assertRaises(ValueError):
                metadata_rows(catalog)

    def test_export_hash_matches_and_existing_directory_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "bundle"
            with patch("scripts.export_catalog_metadata.audit", return_value=report()), patch(
                "scripts.export_catalog_metadata.load_bundle",
                return_value=(None, {"catalog_sha256": "test-catalog-hash"}, [item()]),
            ):
                result = export("unused", output)
                with self.assertRaises(FileExistsError):
                    export("unused", output)
            payload = (output / "materials.jsonl").read_bytes()
            self.assertEqual(result["material_count"], 1)
            self.assertEqual(result["materials_sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(json.loads(payload)["entity_key"], "article:a")

    def test_mismatched_source_blocks_export(self):
        bad = report()
        bad["facet_mapping"]["topics"]["catalog_mapping_mismatch"] = 1
        with tempfile.TemporaryDirectory() as temp, patch(
            "scripts.export_catalog_metadata.audit", return_value=bad
        ):
            output = Path(temp) / "bundle"
            with self.assertRaisesRegex(ValueError, "facets"):
                export("unused", output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
