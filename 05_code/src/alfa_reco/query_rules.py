"""Conservative query transformations for explicit contrast and one ambiguous intent.

These rules are deliberately narrow; they are not a general natural language parser.
"""

import re
from dataclasses import dataclass

from .query_synonyms import canonicalize_phrases
from .text import tokens

CONTRAST_REVERSED = re.compile(r"\bне\s+([^,;.!?]{1,100}?)(?:\s*,\s*|\s+)а\s+", re.I)
CONTRAST_AFTER = re.compile(r"(?:,\s*)?\b(?:а|но)\s+не\s+([^,;.!?]{1,100})", re.I)
ANY_NEGATION = re.compile(r"\b(?:не|без|кроме|исключая|никаких|никакой|not|without)\b", re.I)
COMPLEX_SCOPE = re.compile(r"\b(?:но|однако|зато|если|только|кроме|исключая|не)\b", re.I)
EMPLOYEE = re.compile(r"\b(?:сотрудник|работник|персонал|кадр)\w*", re.I)
RETENTION = re.compile(r"\b(?:удержа|сохран)\w*", re.I)
MONEY = re.compile(
    r"\b(?:алимент|зарплат|заработ|выплат|деньг|денег|долг|налог|штраф|"
    r"доход|нДФЛ|процент|сумм|аванс|исполнител|взыскан|вычет|расчет|расчёт)\w*",
    re.I,
)
PEOPLE_CONTEXT = re.compile(r"\b(?:мотивац|вовлеч|текуч|увольня|лояльност)\w*", re.I)
EMPLOYEE_REWRITE = "мотивация вовлеченность команда сотрудники"
DEBT = re.compile(r"\b(?:долг|задолж)\w*", re.I)
REPAY = re.compile(r"\b(?:закрыт|закрыва|погас|погаш|выплат|уплат|плат|спис|отдат)\w*", re.I)
COLLECT = re.compile(r"\b(?:взыск|дебитор|контрагент|клиент)\w*", re.I)
DEBT_TYPE = re.compile(r"\b(?:налог|кредит|ипотек|аренд|зарплат|сотрудник|поставщик)\w*", re.I)
NO_EXPERIENCE = re.compile(r"\bбез\s+опыт\w*\b", re.I)
FREE_PRICE = re.compile(r"\b(?:бесплатн\w*|без\s+оплат\w*)\b", re.I)


@dataclass(frozen=True)
class QueryPlan:
    retrieval_query: str
    positive_query: str
    excluded_terms: tuple[str, ...] = ()
    contrast_applied: bool = False
    retention_expansion: bool = False
    unresolved_negation: bool = False
    debt_expansion: bool = False
    unsupported_constraints: tuple[str, ...] = ()
    debt_unspecified: bool = False
    synonym_rules: tuple[str, ...] = ()


def plan_query(query):
    positive = query
    negative = ""
    # Support "не клиентов, а сотрудников" as well as "сотрудников, а не клиентов".
    # "Не только X, а также Y" is additive, not an exclusion.
    additive = bool(re.search(r"\bне\s+только\b", positive, re.I))
    match = None if additive else CONTRAST_REVERSED.search(positive)
    if match and COMPLEX_SCOPE.search(match.group(1)):
        match = None
    if match:
        negative = match.group(1)
        positive = positive[: match.start()] + " " + positive[match.end() :]
    else:
        match = None if additive else CONTRAST_AFTER.search(positive)
        if match and COMPLEX_SCOPE.search(match.group(1)):
            match = None
        if match:
            negative = match.group(1)
            positive = positive[: match.start()] + " " + positive[match.end() :]
    positive = " ".join(positive.split()).strip(" ,.;")
    excluded = tuple(sorted(set(tokens(negative)) - set(tokens(positive))))
    # Do not rewrite a query down to an empty string, and do not infer ambiguous scopes.
    if not tokens(positive) or not excluded:
        positive, excluded = query, ()
    # Sentence punctuation must not become part of the last lexical term.
    # Preserve leading dots in technical names such as .NET.
    positive = positive.rstrip(" ,.;!?") or positive
    positive, synonym_rules = canonicalize_phrases(positive)
    retention = bool(
        EMPLOYEE.search(positive) and RETENTION.search(positive) and not MONEY.search(positive)
    )
    unresolved = bool(ANY_NEGATION.search(positive))
    unsupported = []
    retrieval = positive
    if NO_EXPERIENCE.search(retrieval):
        unsupported.append("experience")
        retrieval = NO_EXPERIENCE.sub(" ", retrieval)
    if FREE_PRICE.search(retrieval):
        unsupported.append("price")
        if not re.search(r"\bне\s+бесплатн", retrieval, re.I):
            retrieval = FREE_PRICE.sub(" ", retrieval)
    if re.search(r"\b(?:минут|час(?:а|ов)?|дн(?:я|ей)|недел(?:я|и|ь))\b", positive, re.I):
        unsupported.append("duration")
    if not tokens(retrieval):
        retrieval = positive
    debt = bool(DEBT.search(positive) and REPAY.search(positive) and not COLLECT.search(positive))
    if retention:
        retrieval = f"{retrieval} {EMPLOYEE_REWRITE}"
    if debt:
        retrieval = f"{retrieval} задолженность погасить"
    return QueryPlan(
        " ".join(retrieval.split()),
        positive,
        excluded,
        bool(excluded),
        retention,
        unresolved,
        debt,
        tuple(unsupported),
        bool(debt and not DEBT_TYPE.search(positive)),
        synonym_rules,
    )


def exclusion_multiplier(title_terms, excluded_terms):
    """Demote title conflicts; do not hard-delete documents on keyword evidence alone."""
    return 0.2 if set(title_terms) & set(excluded_terms) else 1.0


def intent_multiplier(title, plan):
    """Demote clear conflicts for supported retention and debt-repayment intents."""
    if plan.retention_expansion and MONEY.search(title) and not PEOPLE_CONTEXT.search(title):
        return 0.2
    if plan.debt_expansion and re.search(r"\b(?:взыск|дебитор)\w*", title, re.I):
        return 0.2
    return 1.0
