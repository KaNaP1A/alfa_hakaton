"""Conservative per-card admission. Rank fusion never proves absolute relevance."""

from .evidence import subject_terms
from .text import tokens

USER_KINDS = frozenset({"article", "course", "document", "podcast", "webinar", "calculator"})
SEMANTIC_MIN = 0.62
ALTERNATIVE_MIN = 0.48
LEXICAL_MIN = 0.85
ACTIONS = set(
    tokens(
        "открыть закрыть начать создать получить выбрать повысить улучшить изучать изучить узнать искать найти"
    )
)


def candidate_support(query, item, cosine=None, lesson_cosine=None, selected=False, conflict=False):
    terms = subject_terms(query)
    card = set(tokens(item["title"] + " " + item.get("description", "")))
    core = terms - ACTIONS or terms
    coverage = len(terms & card) / max(1, len(terms))
    core_match = bool(core & card)
    exact = bool(tokens(query)) and tokens(query.rstrip(" ,.;!?")) == tokens(
        item["title"].rstrip(" ,.;!?")
    )
    lesson_terms = set(
        tokens(
            " ".join(
                lesson.get("title", "") + " " + lesson.get("description", "")
                for lesson in item.get("lessons", [])
            )
        )
    )
    lesson_match = (
        bool(core & lesson_terms) and len(terms & lesson_terms) / max(len(terms), 1) >= LEXICAL_MIN
    )
    semantic = cosine is not None and cosine >= SEMANTIC_MIN and core_match
    lexical = core_match and coverage >= LEXICAL_MIN
    lesson = lesson_match and (lesson_cosine is None or lesson_cosine >= SEMANTIC_MIN)
    accepted = (
        item["kind"] in USER_KINDS
        and not conflict
        and (selected or exact or lexical or semantic or lesson)
    )
    alternative = (
        item["kind"] in USER_KINDS
        and not conflict
        and cosine is not None
        and cosine >= ALTERNATIVE_MIN
    )
    return {
        "admitted": accepted,
        "alternative": not accepted and alternative,
        "card_coverage": round(coverage, 4),
        "card_cosine": round(cosine, 4) if cosine is not None else None,
        "exact_title": exact,
        "explicit_selection": selected,
    }
