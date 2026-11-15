"""Aggregate commercial metadata availability without exporting catalog records."""

import argparse
import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from alfa_reco.bundle import load_bundle
from alfa_reco.eligibility import USER_KINDS
from alfa_reco.pricing import price_fact


def positive_snapshot_amount(value):
    """Count parseable positive snapshot values, without asserting price or currency."""
    if value is None or isinstance(value, bool):
        return False
    try:
        number = Decimal(str(value))
        return number.is_finite() and number > 0
    except (InvalidOperation, ValueError):
        return False


def summarize(catalog):
    by_kind = defaultdict(Counter)
    for item in catalog:
        kind = item.get("kind")
        if kind not in USER_KINDS:
            continue
        row = by_kind[kind]
        row["total"] += 1
        row[f"snapshot_price_{price_fact(item)['status']}"] += 1
        row[f"snapshot_access_{item.get('access_type') or 'unknown'}"] += 1
        row["positive_raw_amount_unverified"] += positive_snapshot_amount(item.get("price_raw"))
        row["visible_lesson_entries"] += len(item.get("lessons") or [])
        row["free_cost_with_non_open_access"] += (
            kind == "course" and price_fact(item)["status"] == "free"
            and item.get("access_type") in {"paid", "subscription"}
        )
    return {
        "searchable_items": sum(row["total"] for row in by_kind.values()),
        "by_kind": {kind: dict(values) for kind, values in sorted(by_kind.items())},
        "limitations": (
            "Aggregate offline snapshot only; raw cost is not a verified current price, "
            "purchase offer, subscription price, entitlement or conversion signal. "
            "No personal events are included."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("artifacts/catalog"))
    args = parser.parse_args()
    _, manifest, catalog = load_bundle(args.catalog)
    result = summarize(catalog)
    result["catalog_sha256"] = manifest["catalog_sha256"]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
