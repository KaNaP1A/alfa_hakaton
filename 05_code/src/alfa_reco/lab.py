"""Read-only local evaluation dashboard, using fixed artifact allowlists."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path, default=None):
    try:
        return json.loads((ROOT / path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def lab_data(route, params):
    pool = ROOT / "artifacts/annotation_pool/relevance_v1/pool.jsonl"
    if route == "/lab/template":
        template = pool.with_name("judgments.jsonl")
        if not template.exists():
            raise ValueError("Пул разметки ещё не подготовлен")
        return {
            "judgments": [json.loads(line) for line in template.read_text().splitlines() if line]
        }
    if route == "/lab/pool":
        if not pool.exists():
            raise ValueError("Пул разметки ещё не подготовлен")
        index = int(params.get("index", 0))
        rows = [json.loads(line) for line in pool.read_text().splitlines() if line]
        if not 0 <= index < len(rows):
            raise ValueError("Invalid query index")
        row = rows[index]
        ratings = ROOT / "artifacts/annotation_pool/relevance_v1/automatic_qwen/ratings.jsonl"
        auto = {}
        if ratings.exists():
            for line in ratings.read_text().splitlines():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r["query_id"] == row["query_id"]:
                    auto[r["entity_key"]] = r
        return {"index": index, "total": len(rows), **row, "automatic_drafts": auto}
    challenge = read(Path("artifacts/challenge_v2/manifest.json"), {})
    reports = {}
    for split in ["dev", "test"]:
        r = read(Path(f"artifacts/challenge_v2/{split}_report.json"))
        if r:
            reports[split] = {
                k: v for k, v in r.items() if k not in {"results", "source_hashes"}
            } | {"examples_failed": [x for x in r["results"] if not x["passed"]][:12]}
    trained = read(Path("artifacts/relevance_v1/training/report.json"), {})
    return {
        "challenge": challenge,
        "reports": reports,
        "annotation_job": read(
            Path("artifacts/annotation_pool/relevance_v1/automatic_qwen/job.json"), {}
        ),
        "training": {
            "selected": trained.get("selected"),
            "training_groups": trained.get("training_groups"),
            "rows": trained.get("training_rows"),
            "quality": {s: d["summary"] for s, d in trained.get("quality", {}).items()},
        },
        "annotation_metrics": read(
            Path("artifacts/annotation_pool/relevance_v1/automatic_qwen/metrics.json"), {}
        ),
        "notice": "Synthetic oracle, automatic real-catalog drafts and human judgments are different evaluation sources.",
    }
