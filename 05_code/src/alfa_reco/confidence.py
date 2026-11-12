"""Presentation status after per-card admission; never a relevance probability."""

from .eligibility import LEXICAL_MIN, SEMANTIC_MIN


def assess_results(results, plans):
    status = {
        "status": "unvalidated" if results else "uncertain",
        "policy": "per_card_v1",
        "semantic_min": SEMANTIC_MIN,
        "lexical_min": LEXICAL_MIN,
    }
    if any(plan.unresolved_negation for plan in plans):
        status.update(status="uncertain", reason="unresolved_negation")
    elif any(plan.unsupported_constraints for plan in plans):
        status.update(status="uncertain", reason="unverified_constraint")
    return status
