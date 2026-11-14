"""Export snapshot metadata for backend integration, without source/user records."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from alfa_reco.cli import KINDS, load_bundle
from alfa_reco.eligibility import USER_KINDS

if __package__:
    from scripts.audit_catalog_facets import audit
else:
    from audit_catalog_facets import audit

FACET_SOURCES = {
    "topics": "ContentSettingsTopics -> Topics.Title",
    "tags": "ContentSettingsTags -> Tags.Title",
    "industries": "ContentSettingsIndustries -> Industries.Title",
}


def metadata_rows(catalog):
    records = []
    seen = set()
    for item in catalog:
        if item.get("kind") not in USER_KINDS:
            continue
        key, source_id, table = item["entity_key"], item["source_id"], item["source_table"]
        if (
            not isinstance(key, str)
            or not isinstance(source_id, str)
            or not source_id
            or key != f"{item['kind']}:{source_id}"
            or KINDS.get(table) != item["kind"]
            or key in seen
        ):
            raise ValueError("Invalid or duplicate material identity")
        seen.add(key)
        if not isinstance(item.get("title"), str) or not item["title"].strip():
            raise ValueError("A material title is required")
        if not isinstance(item.get("description"), str):
            raise ValueError("Description must be a string")
        facets = {}
        for field in FACET_SOURCES:
            values = item.get(field)
            if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
                raise ValueError(f"Invalid {field}")
            if len(set(values)) != len(values):
                raise ValueError(f"Duplicate {field}")
            facets[field] = values
        provenance = item.get("provenance") or {}
        for field, column in (("title", "Title"), ("description", "Description")):
            if provenance.get(field) != f"{table}.{column}":
                raise ValueError(f"Unexpected {field} provenance")
        records.append(
            {
                "entity_key": key,
                "kind": item["kind"],
                "source_id": source_id,
                "title": item["title"],
                "description": item["description"],
                **facets,
                "target_audience": item.get("target_audience", ""),
                "publication_status_snapshot": item.get("publication_status"),
                "access_type_snapshot": item.get("access_type"),
                "data_quality_flags": item.get("data_quality_flags", []),
                "provenance": {
                    "title": provenance["title"],
                    "description": provenance["description"] if item["description"] else None,
                    **{name: source if facets[name] else None for name, source in FACET_SOURCES.items()},
                    "target_audience": "Courses.Target" if item.get("target_audience") else None,
                },
            }
        )
    return sorted(records, key=lambda item: item["entity_key"])


def export(catalog_dir, output):
    report = audit(catalog_dir)
    text = report["title_description_mapping"]
    bad_text = (
        "source_table_or_kind_mismatch",
        "missing_source_record",
        "title_mismatch",
        "description_mismatch",
        "target_audience_mismatch",
    )
    if report["duplicate_entity_keys"] or any(text.get(name, 0) for name in bad_text):
        raise ValueError("Source records do not match the catalog")
    if any(
        values.get("catalog_mapping_mismatch", 0)
        or values.get("unexpected_catalog_values", 0)
        or values.get("multiple_content_settings", 0)
        for values in report["facet_mapping"].values()
    ):
        raise ValueError("Source facets do not match the catalog")
    _, manifest, catalog = load_bundle(catalog_dir)
    if manifest["catalog_sha256"] != report["catalog_sha256"]:
        raise ValueError("Catalog changed during export")
    records = metadata_rows(catalog)
    payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records)
    payload_bytes = payload.encode("utf-8")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "materials.jsonl").write_bytes(payload_bytes)
    result = {
        "schema_version": 1,
        "generation": report["generation"],
        "catalog_sha256": report["catalog_sha256"],
        "materials_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "material_count": len(records),
        "by_kind": dict(Counter(row["kind"] for row in records)),
        "missing_by_field": report["missing_by_field"],
        "note": "Private derived snapshot. No user records, full texts, current rights, prices or verified live URLs. Backend must check current status and entitlements.",
    }
    (output / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("artifacts/catalog"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.catalog, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
