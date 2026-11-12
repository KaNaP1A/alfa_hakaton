"""Grounded, non-causal explanations and conservative coverage signals."""

import re

from .text import tokens

# These describe the request or delivery format, rather than its subject.
GENERIC = {
    "не",
    "без",
    "тольк",
    "такж",
    "ещ",
    "лишь",
    "или",
    "кром",
    "исключ",
    "опыт",
    "курс",
    "курсов",
    "материал",
    "найт",
    "найти",
    "нужн",
    "изучит",
    "изуч",
    "бесплатн",
    "хот",
}


def subject_terms(query):
    return {term for term in tokens(query) if term not in GENERIC and len(term) > 1}


def evidence_for(item, query, ranks, selected=False):
    """Expose verified lexical fields and retrieval channels; never claim true usefulness."""
    terms = subject_terms(query)
    surface = {}
    for match in re.finditer(r"[\w+#.]+", query):
        word = match.group(0)
        for token in tokens(word):
            if token in terms:
                surface.setdefault(token, word)
    fields = [
        ("title", item.get("title", "")),
        ("description", item.get("description", "")),
        ("topics", " ".join(item.get("topics", []) + item.get("tags", []))),
        (
            "lessons",
            " ".join(
                x.get("title", "") + " " + x.get("description", "") for x in item.get("lessons", [])
            ),
        ),
        ("body", item.get("body", "")),
    ]
    facts = []
    seen = set()
    for name, content in fields:
        overlap = (terms & set(tokens(content))) - seen
        if overlap:
            source_words = {}
            for match in re.finditer(r"[\w+#.]+", content):
                for token in tokens(match.group(0)):
                    if token in overlap:
                        source_words.setdefault(token, match.group(0))
            facts.append(
                {
                    "field": name,
                    "query_words": [surface[x] for x in sorted(overlap)],
                    "field_words": [source_words.get(x, x) for x in sorted(overlap)],
                }
            )
            seen |= overlap
    matched = len(seen)
    channels = [name for name, positions in ranks.items() if positions]
    return {
        "facts": facts,
        "matched_subject_terms": matched,
        "subject_terms": len(terms),
        "partial": bool(terms) and matched < len(terms),
        "selection_match": bool(selected),
        "channels": channels,
        "limitation": "Лексическое или смысловое совпадение не гарантирует полезность материала.",
    }


def coverage_signal(query, vocabulary):
    terms = subject_terms(query)
    if not terms:
        return "unknown"
    if not terms & vocabulary:
        return "no_literal_match"
    return "unknown"
