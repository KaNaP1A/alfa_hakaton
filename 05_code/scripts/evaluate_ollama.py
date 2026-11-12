"""Run a reproducible, transparent smoke evaluation against the local Ollama."""

import json
import statistics
import time
from collections import Counter
from pathlib import Path

from alfa_reco.cli import atomic_json
from alfa_reco.query_interpreter import MODEL, OllamaInterpreter, grounded_match


def main():
    root = Path("evaluation")
    cases = json.loads((root / "ollama_scenarios.json").read_text())["cases"]
    interpreter = OllamaInterpreter()
    digest = interpreter.model_digest()
    if not digest:
        raise RuntimeError("Local Ollama model gemma3:1b is not available")
    rows = []
    for case in cases:
        start = time.monotonic()
        result = interpreter.analyze(case["query"])
        elapsed = round(1000 * (time.monotonic() - start), 1)
        # The expected stems are intentionally broad; a match is only a smoke check,
        # not a substitute for a person judging whether the extracted object is correct.
        obj = result.get("object", "").lower()
        expected = case["expected"]
        matched = any(stem.lower() in obj for stem in expected) if expected else None
        rows.append(
            {**case, "result": result, "elapsed_ms": elapsed, "expected_object_match": matched}
        )
        print(f"{len(rows)}/{len(cases)} {result['status']} {elapsed:.0f} ms", flush=True)
        if result.get("negation_present") and grounded_match(result, set(obj.split())) != 0:
            raise RuntimeError("Negated query must not receive a model-derived boost")
    latencies = sorted(row["elapsed_ms"] for row in rows if row["result"]["status"] != "skipped")
    scored = [row for row in rows if row["expected_object_match"] is not None]
    output = {
        "model": MODEL,
        "digest": digest,
        "cases": len(rows),
        "groups": dict(Counter(row["group"] for row in rows)),
        "statuses": dict(Counter(row["result"]["status"] for row in rows)),
        "expected_object_hits": sum(row["expected_object_match"] for row in scored),
        "expected_object_cases": len(scored),
        "median_ms": statistics.median(latencies) if latencies else None,
        "p95_ms": latencies[max(0, (95 * len(latencies) + 99) // 100 - 1)] if latencies else None,
        "caveat": "Broad stem matching is a smoke check only; expected spans and all outputs require independent human review. Timing depends on hardware and load.",
        "results": rows,
    }
    atomic_json(root / "ollama_results" / "report.json", output)
    print(
        json.dumps(
            {k: v for k, v in output.items() if k != "results"}, ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
