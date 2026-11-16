import unittest

from scripts.prepare_persona_corpus import (
    assign_split,
    inferred_tags,
    make_corpus,
    normalize,
    queries,
)


def material(key, title, origin=None):
    row = {
        "entity_key": key,
        "title": title,
        "description": "Курс про финансы и налоги",
        "kind": "course",
        "tags": [],
    }
    if origin:
        row["experiment_origin"] = origin
    return row


class PersonaCorpusTests(unittest.TestCase):
    def test_duplicate_titles_keep_backup_and_quarantine_unverified_public_identity(self):
        base = [
            material("course:1", "Налоги и финансы"),
            material("course:public", "НАЛОГИ И ФИНАНСЫ", "public_snapshot"),
        ]
        catalog, quarantine, stats = make_corpus(base, [], 10)
        self.assertEqual([row["entity_key"] for row in catalog], ["course:1"])
        self.assertEqual(quarantine[0]["entity_key"], "course:public")
        self.assertEqual(quarantine[0]["retained_key"], "course:1")
        self.assertEqual(stats["base_quarantined"], 1)

    def test_external_duplicate_is_not_added_and_does_not_claim_platform_offer(self):
        base = [material("course:1", "Business Finance")]
        hf = [
            {
                "title": "business finance",
                "Description": "Business finance course",
                "URL": "https://www.coursera.org/learn/a",
                "Skills": "['Business']",
            },
            {
                "title": "Data Basics",
                "Description": "Data analysis using Python",
                "URL": "https://www.coursera.org/learn/b",
                "Skills": "['Python']",
            },
            {
                "title": "DATA BASICS",
                "Description": "Another data course",
                "URL": "https://www.coursera.org/learn/c",
                "Skills": "[]",
            },
        ]
        catalog, _, stats = make_corpus(base, hf, 10)
        self.assertEqual(len(catalog), 2)
        self.assertEqual(stats["hf_title_duplicates"], 1)
        external = catalog[1]
        self.assertEqual(external["experiment_origin"], "huggingface_training_only")
        self.assertIsNone(external["price_raw"])
        self.assertIsNone(external["canonical_url"])
        self.assertEqual(external["publication_status"], "unknown")

    def test_synthetic_queries_preserve_held_out_titles_and_do_not_use_protected_ids(self):
        rows = [
            material("course:1", "Курс по налогам"),
            material("course:2", "Управление проектами"),
        ]
        generated = queries(rows, {"course:1"}, per_material=10)
        self.assertTrue(generated)
        self.assertTrue(all(row["target"] == "course:2" for row in generated))
        self.assertTrue(
            all(
                row["synthetic"] and row["label_status"] == "weak_target_preference"
                for row in generated
            )
        )
        self.assertEqual(
            {row["split"] for row in generated}, {assign_split("Управление проектами")}
        )
        self.assertEqual(len({normalize(row["query"]) for row in generated}), len(generated))

    def test_heuristic_tags_include_the_matching_evidence(self):
        self.assertIn(
            {"tag": "Финансы и налоги", "evidence": ["налог"]}, inferred_tags("Курс по налогам", "")
        )


if __name__ == "__main__":
    unittest.main()
