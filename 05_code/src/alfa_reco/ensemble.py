"""Weighted rank fusion for three correlated rankers; scores are not probabilities."""

import math

METHODS = ("bm25", "hybrid", "catboost")
RRF_K = 60


def validate_weights(weights):
    if set(weights) != set(METHODS):
        raise ValueError("Ensemble must define all three method weights")
    if any(type(w) not in (int, float) or not math.isfinite(w) or w < 0 for w in weights.values()):
        raise ValueError("Ensemble weights must be finite and nonnegative")
    if not math.isclose(sum(weights.values()), 1, abs_tol=1e-8):
        raise ValueError("Ensemble weights must sum to one")


def fuse(rankings, weights, k=RRF_K):
    validate_weights(weights)
    if set(rankings) != set(METHODS):
        raise ValueError("Three ranked lists are required")
    if type(k) is not int or not 1 <= k <= 1000:
        raise ValueError("Invalid fusion constant")
    scores = {}
    contributions = {}
    for method in METHODS:
        seen = set()
        for rank, item in enumerate(rankings[method], start=1):
            if item in seen:
                raise ValueError("Duplicate item in ranked list")
            seen.add(item)
            if weights[method] == 0:
                continue
            value = weights[method] * (k + 1) / (k + rank)
            scores[item] = scores.get(item, 0.0) + value
            contributions.setdefault(item, {})[method] = value
    return scores, contributions
