"""Audit displayed source exposure in a saved search stress report."""

import argparse
import json
from collections import Counter
from pathlib import Path

from alfa_reco.bundle import atomic_json, load_bundle, sha256


def summarize_exposure(rows, catalog):
    origins = {item["entity_key"]: item.get("experiment_origin", "backup") for item in catalog}
    model_names = set(rows[0]["models"]) if rows else set()
    if any(set(row["models"]) != model_names for row in rows):
        raise ValueError("Inconsistent models across queries")
    result = {}
    for model in sorted(model_names):
        counts = Counter()
        query_counts = Counter()
        total = 0
        for row in rows:
            keys = row["models"][model]["result_ids"]
            if len(keys) != len(set(keys)):
                raise ValueError("Duplicate material within a result list")
            present = set()
            for key in keys:
                if key not in origins:
                    raise ValueError("Result does not belong to catalog")
                origin = origins[key]
                counts[origin] += 1
                total += 1
                present.add(origin)
            query_counts.update(sorted(present))
        result[model] = {
            "queries": len(rows),
            "shown_cards": total,
            "origin_counts": dict(counts),
            "origin_shares": {name: count / total for name, count in counts.items()}
            if total
            else {},
            "queries_with_origin": dict(query_counts),
        }
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise ValueError("Output already exists")
    _, manifest, catalog = load_bundle(a.catalog)
    report = json.loads(a.report.read_text())
    if report["catalog_sha256"] != manifest["catalog_sha256"]:
        raise ValueError("Catalog hash mismatch")
    summary = summarize_exposure(report["rows"], catalog)
    atomic_json(
        a.output,
        {
            "catalog_sha256": manifest["catalog_sha256"],
            "stress_report_sha256": sha256(a.report),
            "summary": summary,
            "limitations": "Assistant-authored correlated queries. Exposure counts are not quality, purchases, retention or real-user traffic.",
        },
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
