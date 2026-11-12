"""Versioned Russian morphology and conservative order normalization for the ML profile."""

import re
from functools import lru_cache

from .query_rules import plan_query
from .text import STOP, words

VERSION = "ru_morph_clauses_v1"
PROTECTED = frozenset(
    {
        "не",
        "без",
        "кроме",
        "исключая",
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
        "если",
        "чтобы",
        "чем",
        "not",
        "without",
    }
)
SCAFFOLD = STOP | {"нужна", "нужны", "нужное", "нужный", "хотеть", "планировать", "интересовать"}


class Morphology:
    def __init__(self):
        import pymorphy3

        self.analyzer = pymorphy3.MorphAnalyzer()
        self.parse = lru_cache(maxsize=100000)(self._parse)

    def _parse(self, word):
        word = word.casefold().replace("ё", "е")
        if not re.fullmatch("[а-я]+", word):
            return word, ""
        parsed = self.analyzer.parse(word)[0]
        return parsed.normal_form.replace("ё", "е"), str(parsed.tag.POS or "")

    def lemmas(self, text):
        return [self.parse(w)[0] for w in words(text) if w not in STOP]

    def text(self, text):
        return " ".join(self.lemmas(text))

    def query_view(self, query, canonical=True):
        plan = plan_query(query)
        text = plan.retrieval_query
        surface = words(text)
        protected = bool(PROTECTED & set(surface)) or any(
            c in text for c in ('"', "«", "»", ":", ";")
        )
        lexical = self.text(text)
        reason = "protected_relationship" if protected else "surface"
        semantic = " ".join(surface)
        # A finite verb can encode who acts on whom. Never reorder that statement.
        finite = any(self.parse(w)[1] == "VERB" and w not in {"хочу", "планирую"} for w in surface)
        clauses = re.split(r"\s+и\s+", text.casefold())
        parsed_clauses = [
            [w for w in words(c) if w not in STOP and self.parse(w)[0] not in SCAFFOLD]
            for c in clauses
        ]
        infinitives = [sum(self.parse(w)[1] == "INFN" for w in c) for c in parsed_clauses]
        # Keep separate action-object clauses intact: selling a shop and buying
        # equipment must not equal selling equipment and buying a shop.
        safe = (
            not protected
            and not finite
            and all(n <= 1 for n in infinitives)
            and all(parsed_clauses)
            and len(surface) <= 45
        )
        if canonical and safe:
            semantic = " ; ".join(sorted(" ".join(sorted(c)) for c in parsed_clauses))
            reason = "canonical_goal_clauses"
        return {
            "lexical": lexical,
            "semantic": semantic,
            "canonicalized": canonical and safe,
            "normalization": reason,
            "plan": plan,
        }
