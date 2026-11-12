"""Measure the narrow literal-match warning on provisional, manually authored cases."""

import argparse
import json
from pathlib import Path

from alfa_reco.cli import atomic_json, load_bundle
from alfa_reco.evidence import coverage_signal
from alfa_reco.retrieval import FieldRetriever


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists")
    cases = json.loads(Path("evaluation/coverage_probe_cases.json").read_text())["cases"]
    _, manifest, catalog = load_bundle("artifacts/catalog")
    vocabulary = set().union(*FieldRetriever(catalog).context_terms)
    rows = [{**case, "signal": coverage_signal(case["query"], vocabulary)} for case in cases]
    absent = [row for row in rows if row["likely"] == "absent"]
    present = [row for row in rows if row["likely"] == "present"]
    report = {
        "catalog_sha256": manifest["catalog_sha256"],
        "cases": len(rows),
        "likely_absent_flagged": sum(x["signal"] == "no_literal_match" for x in absent),
        "likely_absent_total": len(absent),
        "likely_present_flagged": sum(x["signal"] == "no_literal_match" for x in present),
        "likely_present_total": len(present),
        "caveat": "Проверка ассистента, не независимая разметка и не факт отсутствия ответа в полном каталоге или на сайте. Сигнал только о буквальных совпадениях, не семантическая уверенность.",
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, report)
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "results"}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
