"""Synthetic-only commercial reranking experiment; not a purchase predictor for production."""
import math
from datetime import UTC, datetime

FEATURES = ["base_rank_percentile", "log_price_rub", "budget_known", "log_budget_rub", "price_to_budget"]


def eligible(offer, now):
    """Require backend-confirmed, non-expired, purchasable, unowned RUB offers."""
    if not isinstance(offer, dict) or now.tzinfo is None:
        return False
    if (not isinstance(offer.get("entity_key"), str) or not offer["entity_key"]
            or not isinstance(offer.get("offer_id"), str) or not offer["offer_id"]
            or offer.get("kind") not in {"course", "lesson"}
            or offer.get("currency") != "RUB" or offer.get("verified") is not True
            or offer.get("purchasable") is not True or offer.get("owned") is not False
            or type(offer.get("price_minor")) is not int or offer["price_minor"] <= 0):
        return False
    try:
        expires = datetime.fromisoformat(offer["valid_until"].replace("Z", "+00:00"))
        return expires.tzinfo is not None and expires > now
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def features(rank, total, price_minor, budget_minor=None):
    if type(price_minor) is not int or price_minor <= 0:
        raise ValueError("price_minor must be a positive integer")
    if budget_minor is not None and (type(budget_minor) is not int or budget_minor <= 0):
        raise ValueError("budget_minor must be a positive integer or None")
    price = price_minor / 100
    budget = budget_minor / 100 if budget_minor is not None else 0.0
    return [rank / max(total - 1, 1), math.log1p(price), float(budget_minor is not None),
            math.log1p(budget), min(price / budget, 10.0) if budget else 0.0]


def rerank_synthetic_only(offers, model, *, budget_minor=None, now=None, min_gap=0.18, max_price_minor=None):
    """Rerank eligible already-relevant offers, moving each at most one position.

    Model is trained exclusively on synthetic users: output is NOT real purchase
    probability, and this function is not wired into search or the HTTP API.
    """
    now = now or datetime.now(UTC)
    if not 0 <= min_gap <= 1:
        raise ValueError("min_gap must be between 0 and 1")
    ids = [o.get("offer_id") for o in offers if isinstance(o, dict) and o.get("offer_id")]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate offer_id")
    if max_price_minor is not None and (type(max_price_minor) is not int or max_price_minor <= 0):
        raise ValueError("max_price_minor must be a positive integer or None")
    verified = [dict(o) for o in offers if eligible(o, now)]
    if not verified:
        return {"status": "no_verified_offers", "results": [], "synthetic_only": True}
    selected = [o for o in verified
                if max_price_minor is None or o["price_minor"] <= max_price_minor]
    if not selected:
        return {"status": "no_offers_within_budget", "results": [], "synthetic_only": True}
    x = [features(i, len(selected), o["price_minor"], budget_minor) for i, o in enumerate(selected)]
    predictions = model.predict_proba(x)
    probabilities = [float(p[1]) for p in predictions]
    raw = [p * offer["price_minor"] for p, offer in zip(probabilities, selected, strict=True)]
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in probabilities):
        raise ValueError("Invalid model output")
    low, high = min(raw), max(raw)
    revenue = [(value - low) / (high - low) if high > low else 0.0 for value in raw]
    # Synthetic conversion preference dominates the weaker value signal. Neither is calibrated.
    signals = [0.8 * p + 0.2 * r for p, r in zip(probabilities, revenue, strict=True)]
    result = [{**offer, "synthetic_commercial_signal": round(signal, 6),
               "original_position": i + 1} for i, (offer, signal) in enumerate(zip(selected, signals, strict=True))]
    i = 0
    while i + 1 < len(result):
        a, b = result[i], result[i + 1]
        # Course preference is small; it never bypasses the relevance order by more than one place.
        bonus = 0.05 * ((b["kind"] == "course") - (a["kind"] == "course"))
        if b["synthetic_commercial_signal"] - a["synthetic_commercial_signal"] + bonus > min_gap:
            result[i], result[i + 1] = b, a
        i += 2
    return {"status": "ok", "results": result, "synthetic_only": True}
