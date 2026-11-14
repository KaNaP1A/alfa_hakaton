"""Small, observable request rules applied outside the frozen relevance model.

These patterns are not a general syntactic or semantic parser. In particular, a
match in a title does not prove the scope or intent of the full material.
"""

import re

from .query_rules import ANY_NEGATION, DEBT, EMPLOYEE, MONEY
from .text import tokens

FORMAT_WORDS = {
    "course": r"курс(?:а|у|ы|ов|ом|е)?",
    "webinar": r"вебинар(?:а|у|ы|ов|ом|е)?",
    "article": r"стать(?:я|ю|и|е|ёй|ей)",
    "podcast": r"подкаст(?:а|у|ы|ов|ом|е)?",
    "calculator": r"калькулятор(?:а|у|ы|ов|ом|е)?",
    "document": r"документ(?:а|у|ы|ов|ом|е)?",
}
FORMATS = "|".join(f"(?P<{kind}>{pattern})" for kind, pattern in FORMAT_WORDS.items())
FORMAT_PREFIX = re.compile(
    rf"^\s*(?:(?:я\s+)?(?:хочу|ищу|найди|найдите|подбери|подберите|посоветуй|посоветуйте|покажи|покажите|нужен|нужна|нужно|нужны)\s+"
    rf"(?:мне\s+)?)?(?:(?:бесплатн\w*|платн\w*|онлайн|коротк\w*)\s+)*"
    rf"(?:{FORMATS})\s+(?:по|про|о|об|для)\s+",
    re.I,
)
ALL_FORMATS = re.compile(rf"\b(?:{'|'.join(FORMAT_WORDS.values())})\b", re.I)
ALTERNATIVE_FORMAT = re.compile(r"\b(?:или|либо)\b", re.I)
PRICE = re.compile(r"\b(?:платн\w*|бесплатн\w*|без\s+оплат\w*|за\s+деньги)\b", re.I)
EXPERIENCE = re.compile(
    r"\b(?:для\s+(?:начинающ\w*|новичк\w*|опытн\w*)|"
    r"без\s+(?:(?:предварительн\w*|больш\w*)\s+)?опыт\w*|"
    r"начальн\w*\s+уровн\w*)\b", re.I,
)
AUDIENCE = re.compile(
    r"\bдля\s+(?:предпринимател\w*|бухгалтер\w*|руководител\w*|сотрудник\w*|работник\w*|ип|"
    r"владельц\w*\s+бизнес\w*|малого\s+бизнес\w*)\b", re.I,
)
DURATION = re.compile(
    r"\b(?:\d+\s*(?:минут\w*|час\w*|дн(?:я|ей|и|ь)|недел\w*)|"
    r"(?:за|до|менее|меньше)\s+(?:день|час|недел\w*|месяц\w*))\b", re.I,
)
RETENTION = re.compile(r"\b(?:удержа\w*|сохран\w*)\b", re.I)
DISMISSAL = re.compile(r"\b(?:уволить|увольнени\w*)\b", re.I)
REPAYMENT = re.compile(r"\b(?:погас\w*|погаш\w*|уплат\w*|отдат\w*)\b", re.I)
COLLECTION = re.compile(r"\bвзыск\w*\b", re.I)
PREVENTION = re.compile(r"\b(?:избеж\w*|предотврат\w*|предупред\w*|профилактик\w*)\b", re.I)
PRONOUN = re.compile(r"\b(?:их|его|её|ее|ними|него|них|ней)\b", re.I)
REFERENTS = frozenset(tokens("сотрудник работник персонал кадры клиент долг задолженность"))
EMPLOYEE_REFERENTS = frozenset(tokens("сотрудник работник персонал кадры"))
TURNOVER = re.compile(r"\bтекучест\w*\b", re.I)
LOWER_TURNOVER = re.compile(r"\b(?:уменьш\w*|сниз\w*|сократ\w*|снижени\w*|сокращени\w*)\b", re.I)
EMPLOYEE_CONTEXT = re.compile(r"\b(?:сотрудник|работник|персонал|кадр|команд)\w*", re.I)
DIRECT_RETENTION = re.compile(
    r"\b(?:удержа\w*|текучест\w*|увольня(?:ются|ется|лись|лся|ться)|мотивац\w*|мотивир\w*|вовлеч\w*)\b", re.I,
)
MANAGEMENT_TITLE = re.compile(r"\b(?:управлен\w*|управля\w*|управлять)\b.*\bкоманд\w*\b", re.I)
TEAM_SATISFACTION = re.compile(r"\b(?:довольн\w*|удовлетвор\w*)\b", re.I)
WEAK_INTENT_SEMANTIC_MIN = 0.80


def _match(regex, text):
    match = regex.search(text)
    return match.group(0) if match else None


def actions(text):
    """Recognize only the supported action/object pairs and retain source spans."""
    found = []
    employee = _match(EMPLOYEE, text)
    debt = _match(DEBT, text)
    if employee and not MONEY.search(text):
        for name, pattern in (("retain_employees", RETENTION), ("dismiss_employees", DISMISSAL)):
            action = _match(pattern, text)
            if action:
                found.append({"kind": name, "action": action, "object": employee})
    if employee and TURNOVER.search(text) and LOWER_TURNOVER.search(text):
        action = _match(LOWER_TURNOVER, text)
        if not any(row["kind"] == "retain_employees" for row in found):
            found.append({"kind": "retain_employees", "action": action, "object": employee})
    if debt:
        for name, pattern in (("repay_debt", REPAYMENT), ("collect_debt", COLLECTION)):
            action = _match(pattern, text)
            if action:
                found.append({"kind": name, "action": action, "object": debt})
    return found


OPPOSITES = {"retain_employees": "dismiss_employees", "dismiss_employees": "retain_employees",
             "repay_debt": "collect_debt", "collect_debt": "repay_debt"}


def opposite_title_intent(query_actions, title):
    """Flag narrow title conflicts only; ignore negated or preventive titles."""
    if ANY_NEGATION.search(title) or PREVENTION.search(title):
        return False
    requested = {row["kind"] for row in query_actions}
    title_actions = {row["kind"] for row in actions(title)}
    return any(OPPOSITES[kind] in title_actions and kind not in title_actions for kind in requested)


def ambiguous_contrast_reference(plan):
    """A pronoun may refer to a subject removed by a contrast rule."""
    if not plan.contrast_applied:
        return False
    excluded = set(plan.excluded_terms)
    pronoun = PRONOUN.search(plan.positive_query) and REFERENTS.intersection(excluded)
    synonymous_people = EMPLOYEE.search(plan.positive_query) and EMPLOYEE_REFERENTS.intersection(excluded)
    return bool(pronoun or synonymous_people)


def weak_intent_support(query_actions, item, cosine, *, conflict=False):
    """Return the source of a narrow retention hint, not verified relevance."""
    if conflict or cosine is None or cosine < WEAK_INTENT_SEMANTIC_MIN:
        return None
    if {row["kind"] for row in query_actions} != {"retain_employees"}:
        return None
    title = item["title"]
    description = item.get("description") or ""
    if ANY_NEGATION.search(title):
        return None
    if EMPLOYEE_CONTEXT.search(title) and DIRECT_RETENTION.search(title):
        return "title"
    # A legal template mentioning layoffs is not evidence of a retention plan.
    if item.get("kind") == "document":
        return None
    if EMPLOYEE_CONTEXT.search(title + " " + description) and DIRECT_RETENTION.search(description):
        return "description"
    if MANAGEMENT_TITLE.search(title) and EMPLOYEE_CONTEXT.search(description) and TEAM_SATISFACTION.search(description):
        return "related_team_context"
    return None


def analyze_request(query):
    match = FORMAT_PREFIX.match(query)
    mentioned = list(ALL_FORMATS.finditer(query))
    ambiguous_format = len(mentioned) > 1 and bool(ALTERNATIVE_FORMAT.search(query))
    format_kind = match.lastgroup if match and not ambiguous_format else None
    search_query = query[match.end():].strip() if format_kind else query
    if not search_query:
        format_kind, search_query = None, query
    unsupported = []
    for name, pattern in (("price", PRICE), ("experience", EXPERIENCE),
                          ("audience", AUDIENCE), ("duration", DURATION)):
        if pattern.search(query):
            unsupported.append(name)
    if ambiguous_format:
        unsupported.append("format")
    return {
        "format": format_kind,
        "format_text": match.group(format_kind) if format_kind else None,
        "search_query": search_query,
        "unsupported_constraints": unsupported,
        "audience_text": _match(AUDIENCE, query) or _match(EXPERIENCE, query),
    }
