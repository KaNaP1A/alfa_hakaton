"""Create a larger assistant-authored diagnostic set; keep test queries unscored.

The split is reproducible, not a genuinely independent or inaccessible blind test.
"""

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

from alfa_reco.bundle import sha256
from alfa_reco.eligibility import USER_KINDS
from alfa_reco.search import SearchEngine


def jsonl(rows):
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)


def canonical(text):
    return " ".join(re.findall(r"[\w]+", text.casefold().replace("ё", "е")))


def scenarios(seed_path, seed=20261113):
    data = json.loads(seed_path.read_text(encoding="utf-8"))
    if len(data) != 12 or any(len(goals) != 10 for goals in data.values()):
        raise ValueError("Expected 12 areas with 10 tasks each")
    normalized = [canonical(goal) for goals in data.values() for goal in goals]
    if len(normalized) != len(set(normalized)):
        raise ValueError("Duplicate goal")
    rows = []
    for category, goals in sorted(data.items()):
        indices = list(range(len(goals)))
        rng = random.Random(int(hashlib.sha256(f"{seed}:{category}".encode()).hexdigest(), 16))
        rng.shuffle(indices)
        assignment = {
            i: ("train" if n < 6 else "validation" if n < 8 else "test")
            for n, i in enumerate(indices)
        }
        for i, goal in enumerate(goals):
            family = f"{category}_{i + 1:02}"
            formulations = [
                f"Как {goal}?",
                f"Нужно {goal}. С чего начать?",
                f"Для своей ситуации хочу {goal}. Какие материалы помогут?",
            ]
            for j, query in enumerate(formulations, 1):
                rows.append(
                    {
                        "query_id": hashlib.sha256(f"query_v2:{family}:{j}".encode()).hexdigest()[
                            :24
                        ],
                        "family": family,
                        "split": assignment[i],
                        "category": category,
                        "query": query,
                        "origin": "assistant_authored_template",
                        "variant": j,
                    }
                )
    if len({canonical(row["query"]) for row in rows}) != len(rows):
        raise ValueError("Duplicate generated query")
    return rows


def known_texts():
    found = set()
    for path in (
        Path("evaluation/ensemble_cases_v2.json"),
        Path("evaluation/challenge_v2/real_pool_pool.jsonl"),
        Path("artifacts/relevance_v1/training/training_preferences.jsonl"),
    ):
        if not path.exists():
            continue
        if path.suffix == ".jsonl":
            rows = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line
            ]
        else:
            rows = json.loads(path.read_text(encoding="utf-8"))["queries"]
        found.update(canonical(row["query"]) for row in rows if row.get("query"))
    return found


def build(source, output, seed):
    if output.exists():
        raise ValueError("Output exists; do not overwrite a frozen evaluation")
    rows = scenarios(source, seed)
    known = known_texts()
    overlaps = [row for row in rows if canonical(row["query"]) in known]
    if overlaps:
        raise ValueError(f"Exact query overlap with historical data: {len(overlaps)}")
    engine = SearchEngine("artifacts/catalog", semantic=False, llm_enabled=False)
    backend = engine.relevance_backend()
    ranker = backend.model
    if ranker is None:
        raise ValueError("Relevance ranker missing")
    original_prepare = backend.prepare

    @lru_cache(maxsize=2)
    def cached(query, allowed, selected):
        return original_prepare(query, allowed=set(allowed), selected_keys=selected)

    def prepare(query, allowed=None, selected_keys=(), vector=None):
        if allowed is None or vector is not None:
            return original_prepare(
                query, allowed=allowed, selected_keys=selected_keys, vector=vector
            )
        return cached(query, tuple(sorted(allowed)), tuple(sorted(selected_keys)))

    backend.prepare = prepare
    catalog = [item for item in engine.catalog if item["kind"] in USER_KINDS]
    pool, rankings, judgments = [], [], []
    active = [row for row in rows if row["split"] != "test"]
    for number, case in enumerate(active, 1):
        qid, query = case["query_id"], case["query"]
        candidates, orders = {}, {}
        try:
            for method in ("e5_without_ranker", "relevance"):
                backend.model = None if method == "e5_without_ranker" else ranker
                result = engine.search(query, mode="relevance", top=5)
                orders[method] = [item["entity_key"] for item in result["results"]]
                for item in result["results"] + result["alternatives"]:
                    candidates[item["entity_key"]] = {
                        k: item[k] for k in ("entity_key", "title", "description", "kind")
                    }
        finally:
            backend.model = ranker
        rng = random.Random(int(hashlib.sha256(f"{seed}:{qid}:random".encode()).hexdigest(), 16))
        for item in rng.sample(catalog, min(3, len(catalog))):
            candidates[item["entity_key"]] = {
                k: item[k] for k in ("entity_key", "title", "description", "kind")
            }
        ordered = sorted(
            candidates.values(),
            key=lambda x: hashlib.sha256(f"{seed}:{qid}:{x['entity_key']}".encode()).hexdigest(),
        )
        pool.append({**case, "candidates": ordered})
        rankings.append({"query_id": qid, "rankings": orders})
        judgments.extend(
            {
                "query_id": qid,
                "entity_key": c["entity_key"],
                "reviewer_a": None,
                "reviewer_b": None,
                "adjudicated": None,
            }
            for c in ordered
        )
        if number % 25 == 0:
            print(f"Prepared {number}/{len(active)}", flush=True)
    output.mkdir(parents=True, exist_ok=False)
    files = {
        "pool.jsonl": pool,
        "rankings.jsonl": rankings,
        "judgments.jsonl": judgments,
        "test_queries_unscored.jsonl": [row for row in rows if row["split"] == "test"],
    }
    hashes = {}
    for name, values in files.items():
        path = output / name
        path.write_text(jsonl(values), encoding="utf-8")
        hashes[name] = sha256(path)
    split_counts = dict(Counter(row["split"] for row in rows))
    manifest = {
        "schema_version": 1,
        "purpose": "assistant_authored_development_and_provisional_holdout_not_independent",
        "catalog_generation": engine.generation,
        "catalog_sha256": engine.manifest["catalog_sha256"],
        "model_manifest_sha256": sha256(backend.path / "manifest.json"),
        "source_seed_sha256": sha256(source),
        "builder_sha256": sha256(Path(__file__)),
        "code_hashes": {p.name: sha256(p) for p in sorted(Path("src/alfa_reco").glob("*.py"))},
        "seed": seed,
        "python": sys.version.split()[0],
        "queries": len(rows),
        "families": len({r["family"] for r in rows}),
        "categories": len({r["category"] for r in rows}),
        "split_counts": split_counts,
        "candidates_development": len(judgments),
        "old_exact_overlap": len(overlaps),
        "holdout_rankings_created": False,
        "returned_development": {
            method: dict(Counter(len(r["rankings"][method]) for r in rankings))
            for method in ("e5_without_ranker", "relevance")
        },
        "hashes_before_review": hashes,
        "note": "120 assistant-authored seed tasks x 3 template variants, not 360 independent intents. No labels. Exact-match audit does not rule out semantic overlap. Test queries exist on disk and were authored during development; not a blind or independent human test. Test rankings intentionally not generated.",
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("evaluation/query_goals_v2.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261113)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output, args.seed), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
