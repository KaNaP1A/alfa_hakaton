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
