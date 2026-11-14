"""Compare catalog facets with the frozen source snapshot, without changing either."""

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

from alfa_reco.bundle import sha256
from alfa_reco.cli import KINDS, clean, load_bundle
from alfa_reco.eligibility import USER_KINDS


def fetch(connection, table):
    # All table identifiers are fixed in this script.
    return [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]  # noqa: S608


def audit(catalog_dir):
    generation, manifest, catalog = load_bundle(catalog_dir)
    eligible = [item for item in catalog if item["kind"] in USER_KINDS]
    source_path = generation / "source.sqlite"
    if not source_path.is_file():
        raise ValueError("Source snapshot is unavailable")
    if sha256(source_path) != manifest["source_sqlite_sha256"]:
        raise ValueError("Source snapshot hash mismatch")
    with closing(sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        source_tables = {
            table: {row["Id"]: row for row in fetch(db, table)} for table in KINDS
        }
        text_counts = Counter()
        for item in eligible:
            table = item["source_table"]
            if table not in source_tables or KINDS[table] != item["kind"]:
                text_counts["source_table_or_kind_mismatch"] += 1
                continue
            source = source_tables[table].get(item["source_id"])
            if source is None:
                text_counts["missing_source_record"] += 1
                continue
            for field, column in (("title", "Title"), ("description", "Description")):
                if clean(source.get(column)) != item.get(field):
                    text_counts[field + "_mismatch"] += 1
                else:
                    text_counts[field + "_matches"] += 1
                text_counts[field + "_missing"] += not bool(item.get(field))
            expected_audience = clean(source.get("Target")) if item["kind"] == "course" else ""
            if expected_audience != item.get("target_audience", ""):
                text_counts["target_audience_mismatch"] += 1
            else:
                text_counts["target_audience_matches"] += 1
        settings = defaultdict(list)
        for row in fetch(db, "ContentSettings"):
            settings[row["EntityId"]].append(row)
        breakdown = {}
        for field, table, join_key in (
            ("topics", "Topics", "TopicId"),
            ("tags", "Tags", "TagId"),
            ("industries", "Industries", "IndustryId"),
        ):
            labels = {row["Id"]: row for row in fetch(db, table)}
            links = defaultdict(list)
            for row in fetch(db, "ContentSettings" + table):
                links[row["ContentSettingsId"]].append(row)
            counts = Counter()
            for item in eligible:
                setting = settings[item["source_id"]]
                if not setting:
                    counts["no_content_settings"] += 1
                    counts["unexpected_catalog_values"] += bool(item.get(field))
                    continue
                if len(setting) > 1:
                    counts["multiple_content_settings"] += 1
                    continue
                raw = links[setting[0]["Id"]]
                if not raw:
                    counts["no_source_links"] += 1
                    counts["unexpected_catalog_values"] += bool(item.get(field))
                    continue
                accepted = sorted(
                    {
                        clean(labels[row[join_key]]["Title"])
                        for row in raw
                        if row.get("IsDeleted") != "t"
                        and row[join_key] in labels
                        and labels[row[join_key]].get("IsDeleted") != "t"
                        and labels[row[join_key]].get("IsPublic") != "f"
                    }
                )
                if not accepted:
                    counts["all_source_links_filtered_or_invalid"] += 1
                    counts["unexpected_catalog_values"] += bool(item.get(field))
                    reasons = set()
                    for row in raw:
                        label = labels.get(row[join_key])
                        if label is None:
                            reasons.add("missing_label")
                        else:
                            if label.get("IsDeleted") == "t" or row.get("IsDeleted") == "t":
                                reasons.add("deleted")
                            if label.get("IsPublic") == "f":
                                reasons.add("nonpublic")
                    counts["filtered_nonpublic"] += "nonpublic" in reasons
                    counts["filtered_deleted"] += "deleted" in reasons
                    counts["filtered_missing_label"] += "missing_label" in reasons
                elif accepted != item.get(field):
                    counts["catalog_mapping_mismatch"] += 1
                else:
                    counts["catalog_mapping_matches"] += 1
            breakdown[field] = dict(counts)
    return {
        "generation": generation.name,
        "catalog_sha256": manifest["catalog_sha256"],
        "catalog_items": len(catalog),
        "eligible_items": len(eligible),
        "eligible_by_kind": dict(Counter(item["kind"] for item in eligible)),
        "missing_by_field": {
            field: sum(not bool(item.get(field)) for item in eligible)
            for field in ("title", "description", "topics", "tags", "industries", "body")
        },
        "duplicate_entity_keys": len(catalog) - len({item["entity_key"] for item in catalog}),
        "title_description_mapping": dict(text_counts),
        "facet_mapping": breakdown,
        "note": "Snapshot comparison only. Current publication, price, URLs and access were not checked. Counts of filtered reasons may overlap.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
