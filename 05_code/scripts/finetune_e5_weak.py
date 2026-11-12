#!/usr/bin/env python3
"""Isolated E5 experiment; weak labels, source-title splits, never activates a model."""
import argparse
import hashlib
import json
import math
import random
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from alfa_reco.eligibility import USER_KINDS
from alfa_reco.relevance import card_text
from alfa_reco.relevance_text import Morphology
from alfa_reco.search import SearchEngine


def source_group(title):
    return " ".join(title.casefold().split())


def split_groups(rows, items, seed=42):
    groups = sorted({source_group(items[r["entity_keys"][0]]["title"]) for r in rows})
    random.Random(seed).shuffle(groups)
    first, second = int(len(groups) * .6), int(len(groups) * .8)
    assignment = {group: split for split, chunk in (("train", groups[:first]),
                  ("validation", groups[first:second]), ("test", groups[second:]))
                  for group in chunk}
    return {split: [r for r in rows if assignment[source_group(items[r["entity_keys"][0]]["title"])] == split]
            for split in ("train", "validation", "test")}, assignment


def metrics(model, items, rows, morph, batch_size):
    model.eval()
    passages = model.encode(["passage: " + card_text(item) for item in items],
                            normalize_embeddings=True, batch_size=batch_size, show_progress_bar=False)
    queries = model.encode(["query: " + morph.query_view(row["query"], True)["semantic"] for row in rows],
                           normalize_embeddings=True, batch_size=batch_size, show_progress_bar=False)
    lookup = {item["entity_key"]: index for index, item in enumerate(items)}
    scores = queries @ passages.T
    ranks = [int(np.count_nonzero(scores[i] > scores[i, lookup[row["entity_keys"][0]]])) + 1
             for i, row in enumerate(rows)]
    return {"queries": len(rows), "ndcg_at_5": float(np.mean([1 / math.log2(r + 1) if r <= 5 else 0 for r in ranks])),
            "mrr_at_10": float(np.mean([1 / r if r <= 10 else 0 for r in ranks])),
            "recall_at_10": float(np.mean([r <= 10 for r in ranks]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="artifacts/catalog")
    parser.add_argument("--preferences", default="artifacts/relevance_v1/training/training_preferences.jsonl")
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=0.00002)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(2)
    engine = SearchEngine(args.catalog)
    backend = engine.relevance_backend()
    items = [x for x in engine.catalog if x["kind"] in USER_KINDS]
    by_key = {x["entity_key"]: x for x in items}
    rows = [json.loads(line) for line in Path(args.preferences).read_text().splitlines()]
    rows = [row for row in rows if row["source"] == "synthetic" and row["entity_keys"][0] in by_key]
    splits, assignment = split_groups(rows, by_key, args.seed)
    held_groups = {group for group, split in assignment.items() if split != "train"}
    pairs = []
    for row in splits["train"]:
        negatives = [key for key in row["entity_keys"][1:] if key in by_key
                     and source_group(by_key[key]["title"]) not in held_groups]
        if negatives:
            pairs.append((row["query"], row["entity_keys"][0], random.choice(negatives)))
    if not pairs or not splits["test"] or not splits["validation"]:
        raise ValueError("Empty split")
    manifest = {"seed": args.seed, "method": "source normalized-title group split 60/20/20",
                "group_counts": {s: sum(v == s for v in assignment.values()) for s in splits},
                "query_counts": {s: len(v) for s, v in splits.items()}, "train_pairs": len(pairs),
                "preferences_sha256": hashlib.sha256(Path(args.preferences).read_bytes()).hexdigest(),
                "learning_rate": args.learning_rate, "batch_size": args.batch_size,
                "max_length_train": args.max_length, "epochs": 1,
                "limitations": "Weak source-document labels; no human judgments. Previously used by CatBoost; E5 is pretrained on unknown data. Title grouping does not prove semantic independence."}
    (out / "split_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    morph = Morphology()
    encoder_path = backend.manifest["encoder_path"]
    model = backend.encoder
    model.max_seq_length = 384
    print("Baseline validation", flush=True)
    baseline_val = metrics(model, items, splits["validation"], morph, args.batch_size)
    print(json.dumps(baseline_val), flush=True)
    model.max_seq_length = args.max_length
    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    random.shuffle(pairs)
    for offset in range(0, len(pairs), args.batch_size):
        batch = pairs[offset:offset + args.batch_size]
        qs = ["query: " + morph.query_view(q, True)["semantic"] for q, _, _ in batch]
        ps = ["passage: " + card_text(by_key[p]) for _, p, _ in batch]
        ns = ["passage: " + card_text(by_key[n]) for _, _, n in batch]
        qv, pv, nv = [torch.nn.functional.normalize(model(model.tokenize(texts))["sentence_embedding"], dim=1)
                      for texts in (qs, ps, ns)]
        loss = -torch.nn.functional.logsigmoid(((qv * pv).sum(dim=1) - (qv * nv).sum(dim=1)) / .05).mean()
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        if offset % (args.batch_size * 10) == 0:
            print(f"train {min(offset + len(batch), len(pairs))}/{len(pairs)} loss={loss.item():.4f}", flush=True)
    model.eval()
    model.max_seq_length = 384
    print("Candidate validation", flush=True)
    candidate_val = metrics(model, items, splits["validation"], morph, args.batch_size)
    # Fixed selection rule, before test access. A weak validation improvement is not deployment approval.
    selected = candidate_val["ndcg_at_5"] > baseline_val["ndcg_at_5"]
    (out / "selection.json").write_text(json.dumps({"baseline": baseline_val, "candidate": candidate_val,
        "selected_candidate": selected, "rule": "candidate NDCG@5 strictly greater than baseline"}, indent=2))
    model.save(str(out / "candidate_encoder"))
    print("Final weak test: candidate", flush=True)
    candidate_test = metrics(model, items, splits["test"], morph, args.batch_size)
    del optimizer, model, backend, engine
    model = SentenceTransformer(encoder_path, device="cpu", local_files_only=True)
    model.max_seq_length = 384
    print("Final weak test: baseline", flush=True)
    baseline_test = metrics(model, items, splits["test"], morph, args.batch_size)
    result = {"baseline_validation": baseline_val, "candidate_validation": candidate_val,
              "selected_candidate": selected, "baseline_test": baseline_test, "candidate_test": candidate_test,
              "activated": False, "notice": manifest["limitations"]}
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
