"""Compare real displayed results on a fixed, incompletely labelled stress set."""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from catboost import CatBoostRanker

from alfa_reco.bundle import atomic_json, sha256
from alfa_reco.search import SearchEngine


def summarize(rows, name):
    values = [r["models"][name] for r in rows]
    return {
        "queries": len(values),
        "known_target_shown_top5": sum(v["known_target_shown"] for v in values),
        "known_target_shown_rate": mean(v["known_target_shown"] for v in values)
        if values
        else None,
        "known_target_retrieved": sum(v["known_target_retrieved"] for v in values),
        "empty_results": sum(not v["result_ids"] for v in values),
        "duplicate_result_queries": sum(
            len(v["result_ids"]) != len(set(v["result_ids"])) for v in values
        ),
    }


def evaluate(engine, cases, models):
    backend = engine.relevance_backend()
    original_prepare = backend.prepare
    cache = {}
    original_result = backend.result
    captured = {}

    def cached_prepare(query, allowed=None, selected_keys=(), vector=None):
        if vector is not None:
            return original_prepare(query, allowed, selected_keys, vector)
        key = (query, None if allowed is None else frozenset(allowed), tuple(sorted(selected_keys)))
        if key not in cache:
            cache[key] = original_prepare(query, allowed, selected_keys)
        return cache[key]

    def capture_result(*args, **kwargs):
        value = original_result(*args, **kwargs)
        captured["retrieved"] = {engine.catalog[i]["entity_key"] for i in value["candidates"]}
        return value

    backend.prepare = cached_prepare
    backend.result = capture_result
    out = []
    for number, row in enumerate(cases, 1):
        cache.clear()
        targets = set(row["known_targets"])
        result = {}
        for name, model in models.items():
            backend.model = model
            captured.clear()
            response = engine.search(row["query"], mode="relevance", top=5)
            keys = [x["entity_key"] for x in response["results"]]
            result[name] = {
                "result_ids": keys,
                "known_target_shown": bool(targets & set(keys)),
                "known_target_retrieved": bool(targets & captured.get("retrieved", set())),
                "diagnostics": response["retrieval_diagnostics"],
            }
        out.append({**row, "models": result})
        if number % 10 == 0:
            print(f"Queries {number}/{len(cases)}", flush=True)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--queries", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise ValueError("Output already exists")
    data = json.loads(a.queries.read_text())
    engine = SearchEngine(a.catalog)
    if data["catalog_sha256"] != engine.manifest["catalog_sha256"]:
        raise ValueError("Catalog hash mismatch")
    backend = engine.relevance_backend()
    candidate = CatBoostRanker()
    candidate.load_model(str(a.candidate))
    models = {"baseline": backend.model, "blend": candidate}
    rows = evaluate(engine, data["queries"], models)
    summary = {name: summarize(rows, name) for name in models}
    by_split = {
        split: {
            name: summarize([r for r in rows if r["original_split"] == split], name)
            for name in models
        }
        for split in sorted({r["original_split"] for r in rows})
    }
    family = {}
    for f in sorted({r["family"] for r in rows}):
        subset = [r for r in rows if r["family"] == f]
        family[f] = {name: summarize(subset, name) for name in models}
    by_style = {}
    paired = {}
    if all("style" in r and "base_id" in r for r in rows):
        styles = sorted({r["style"] for r in rows})
        by_style = {
            style: {
                name: summarize([r for r in rows if r["style"] == style], name) for name in models
            }
            for style in styles
        }
        groups = defaultdict(dict)
        for row in rows:
            if row["style"] in groups[row["base_id"]]:
                raise ValueError("Duplicate style within group")
            groups[row["base_id"]][row["style"]] = row
        if any(set(g) != set(styles) or "original" not in g for g in groups.values()):
            raise ValueError("Incomplete paired styles")
        for style in styles:
            if style == "original":
                continue
            paired[style] = {}
            for name in models:
                pairs = [
                    (
                        g["original"]["models"][name]["known_target_shown"],
                        g[style]["models"][name]["known_target_shown"],
                    )
                    for g in groups.values()
                ]
                paired[style][name] = {
                    "pairs": len(pairs),
                    "lost_known_target": sum(a and not b for a, b in pairs),
                    "gained_known_target": sum(not a and b for a, b in pairs),
                    "unchanged_known_target_status": sum(a == b for a, b in pairs),
                }
    report = {
        "catalog_sha256": engine.manifest["catalog_sha256"],
        "queries_sha256": sha256(a.queries),
        "candidate_sha256": sha256(a.candidate),
        "summary": summary,
        "by_original_split": by_split,
        "by_family": family,
        "by_style": by_style,
        "paired_styles": paired,
        "rows": rows,
        "limitations": "Assistant-authored paraphrases and provisional target links; same families were seen before. Other relevant documents are not judged: target miss is not proof of irrelevant results, and target hit is not independent quality evidence. Includes full search gate; no conversion measurement.",
    }
    atomic_json(a.output, report)
    print(
        json.dumps(
            {
                "summary": summary,
                "by_original_split": by_split,
                "by_style": by_style,
                "paired_styles": paired,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
