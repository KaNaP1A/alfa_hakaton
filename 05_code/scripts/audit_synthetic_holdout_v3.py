"""Check split and provenance overlap without scoring or changing model selection."""

import json
from pathlib import Path

from build_synthetic_holdout_v3 import textnorm

from alfa_reco.bundle import atomic_json, load_bundle, sha256


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def main():
    root = Path("artifacts/synthetic_holdout_v3")
    manifest = json.loads((root / "manifest.json").read_text())
    for name, digest in manifest["hashes"].items():
        if sha256(root / name) != digest:
            raise ValueError("Dataset hash mismatch: " + name)
    queries = {s: rows(root / s / "queries.jsonl") for s in ["validation", "test"]}
    judgments = {s: rows(root / s / "labels.jsonl") for s in queries}
    docs = {
        s: json.loads((root / s / "catalog/generation-synthetic/catalog.json").read_text())
        for s in queries
    }
    old = json.loads(Path("artifacts/relevance_v1/training/synthetic_queries.json").read_text())
    prior = json.loads(Path("evaluation/ensemble_cases_v2.json").read_text())["queries"]
    old_queries = {textnorm(x["query"]) for x in old} | {
        textnorm(x["query"]) for x in prior if x["split"] == "train"
    }
    _, _, catalog = load_bundle("artifacts/catalog")
    by_id = {x["entity_key"]: x for x in catalog}
    old_titles = {textnorm(by_id[x["target"]]["title"]) for x in old if x["target"] in by_id}
    family = {s: {x["family"] for x in queries[s]} for s in queries}
    ids = {s: {x["entity_key"] for x in docs[s]} for s in queries}
    titles = {s: {textnorm(x["title"]) for x in docs[s]} for s in queries}
    qtext = {s: {textnorm(x["query"]) for x in queries[s]} for s in queries}
    details = {}
    for split in queries:
        byid = {d["entity_key"]: d for d in docs[split]}
        dupes = 0
        for label in judgments[split]:
            a, b = (byid[k] for k in label["positive"])
            dupes += a["title"] == b["title"] and a["description"] == b["description"]
        details[split] = {
            "queries": len(queries[split]),
            "families": len(family[split]),
            "documents": len(docs[split]),
            "exact_queries_in_920_prior_train_candidates": len(qtext[split] & old_queries),
            "document_titles_matching_292_prior_train_targets": len(titles[split] & old_titles),
            "positive_query_pairs_with_identical_card_text": dupes,
            "queries_exactly_embedded_in_any_document": sum(
                any(
                    textnorm(q["query"]) in textnorm(d["title"] + " " + d["description"])
                    for d in docs[split]
                )
                for q in queries[split]
            ),
            "documents_containing_oracle_fields": sum(
                any(k.startswith("oracle_") or k in {"grade", "label", "positive"} for k in d)
                for d in docs[split]
            ),
        }
    audit = {
        "hashes_verified": len(manifest["hashes"]),
        "family_overlap": len(family["validation"] & family["test"]),
        "query_overlap": len(qtext["validation"] & qtext["test"]),
        "document_id_overlap": len(ids["validation"] & ids["test"]),
        "document_title_overlap": len(titles["validation"] & titles["test"]),
        "split": details,
        "limits": "Checks exact normalized text and recorded IDs only; cannot exclude paraphrases, shared concepts, model pretraining overlap, incorrect synthetic judgments, or manual author bias. The two positively labelled cards repeat identical text in different formats.",
    }
    atomic_json(root / "leakage_audit.json", audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
