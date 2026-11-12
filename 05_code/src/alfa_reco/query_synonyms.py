"""Small, auditable phrase equivalences; never expand ambiguous individual words.

These rules change query text only. They do not label documents or modify the
indexed vocabulary and model feature schema. Other paraphrases remain untreated.
"""

import re

PHRASES = (
    (r"управление\s+(?:персоналом|работниками)", "управление сотрудниками"),
    (r"мотивация\s+(?:персонала|работников)", "мотивация сотрудников"),
    (r"поиск\s+(?:персонала|работников)", "поиск сотрудников"),
    (r"на[её]м\s+сотрудников", "найм сотрудников"),
)
RULES = tuple(
    (re.compile(r"(?<!\w)" + pattern + r"(?!\w)", re.I), target) for pattern, target in PHRASES
)


def canonicalize_phrases(query):
    applied = []
    for pattern, target in RULES:
        query, count = pattern.subn(target, query)
        if count:
            applied.append(target)
    return query, tuple(applied)
