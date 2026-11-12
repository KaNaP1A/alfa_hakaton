"""Shared lightweight normalization; not full morphological analysis."""

import re

STOP = {
    "и",
    "в",
    "на",
    "с",
    "к",
    "а",
    "по",
    "для",
    "как",
    "что",
    "это",
    "я",
    "мне",
    "хочу",
    "нужно",
    "нужен",
    "у",
    "о",
    "об",
    "из",
}


def tokens(text):
    result = []
    # Conservative light suffix normalization, not a full lemmatizer.
    suffixes = (
        "иями",
        "ами",
        "ями",
        "ого",
        "ему",
        "ому",
        "ыми",
        "ими",
        "ов",
        "ев",
        "ей",
        "ий",
        "ый",
        "ой",
        "ая",
        "яя",
        "ую",
        "юю",
        "ое",
        "ее",
        "ые",
        "ие",
        "ам",
        "ям",
        "ах",
        "ях",
        "ом",
        "ем",
        "а",
        "я",
        "ы",
        "и",
        "у",
        "ю",
        "е",
        "о",
        "ь",
    )
    for word in re.findall(r"[\w+#.]+", text.lower().replace("ё", "е")):
        if word in STOP:
            continue
        if re.fullmatch("[а-я]+", word):
            for suffix in suffixes:
                if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                    word = word[: -len(suffix)]
                    break
        result.append(word)
    return result


def words(text):
    return re.findall(r"[\w+#]+", text.casefold().replace("ё", "е"))


def embedding_query(text):
    """Canonicalize only short, simple keyword bags, never explicit relationships.

    Retrieval and interpretation retain the original text. Sorting the content words is
    a heuristic, not a claim that all permutations have the same meaning.
    """
    parts = words(text)
    protected = {
        "не",
        "без",
        "кроме",
        "от",
        "до",
        "из",
        "через",
        "против",
        "вместо",
        "между",
        "над",
        "под",
        "после",
        "перед",
    }
    if any(word in protected for word in parts) or any(
        mark in text for mark in ('"', "«", "»", ":", ";", "?")
    ):
        return text
    content = [word for word in parts if word not in STOP]
    if 2 <= len(content) <= 4 and len(parts) <= 8:
        return " ".join(sorted(content))
    return text
