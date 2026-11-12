"""Local, explainable recommendations from explicit interests and catalog views.

This is a cold-start heuristic, not a learned estimate of engagement or revenue.
"""

import math
from collections import Counter

from .text import tokens, words

CATEGORIES = {
    "business": (
        "Открытие и развитие бизнеса",
        {"Старт бизнеса", "Развитие бизнеса", "Первые шаги", "Регистрация бизнеса"},
    ),
    "finance": (
        "Финансы и налоги",
        {"Финансы и учет", "Финансы", "Налоги и законы", "Финансовый анализ", "Законы"},
    ),
    "team": (
        "Команда и управление",
        {"Управление командой", "Поиск сотрудников", "Управление проектами"},
    ),
    "marketing": (
        "Маркетинг и продажи",
        {"Маркетинг", "Продажи", "Продвижение продукта", "Коммуникация с клиентами"},
    ),
    "technology": ("Технологии и данные", {"Технологии", "Анализ данных", "Работа с данными"}),
}


def facets(item):
    return set(item.get("topics", [])) | set(item.get("tags", []))


def title_subjects(title):
    """Discard generic legal forms and infinitives as weak evidence of shared subject."""
    generic = {
        "ип",
        "ооо",
        "компан",
        "организац",
        "проверка",
        "проверк",
        "способ",
        "правил",
        "пример",
        "все",
        "всех",
        "вам",
        "ваш",
        "ваши",
        "наш",
        "наши",
        "чтобы",
        "только",
        "бизнес",
    }
    infinitives = ("ать", "ять", "ить", "еть", "уть", "оть", "чь", "ти")
    return {
        term
        for word in words(title)
        if not word.endswith(infinitives)
        for term in tokens(word)
        if len(term) > 2 and term not in generic
    }


def recommend(catalog, categories, viewed, limit=5, vectors=None):
    if not isinstance(categories, list) or not isinstance(viewed, list):
        raise ValueError("categories and viewed must be lists")
    if (
        len(categories) > len(CATEGORIES)
        or len(viewed) > 50
        or type(limit) is not int
        or not 1 <= limit <= 20
    ):
        raise ValueError("Profile exceeds the supported size")
    if any(not isinstance(x, str) or x not in CATEGORIES for x in categories):
        raise ValueError("Unknown interest category")
    if any(not isinstance(x, str) or len(x) > 150 for x in viewed):
        raise ValueError("Invalid viewed item")
    by_id = {item["entity_key"]: item for item in catalog}
    if any(key not in by_id for key in viewed):
        raise ValueError("Viewed item is not in this catalog generation")
    # Most recent occurrence takes precedence and each item contributes only once.
    recent = list(dict.fromkeys(reversed(viewed)))[:20]
    selected = {name for category in categories for name in CATEGORIES[category][1]}
    viewed_set = set(viewed)
    indices = {item["entity_key"]: i for i, item in enumerate(catalog)}
    semantic = {}
    if vectors is not None and recent:
        for key in recent:
            semantic[key] = vectors @ vectors[indices[key]]
    subjects = {item["entity_key"]: title_subjects(item["title"]) for item in catalog}
    frequency = Counter(term for terms in subjects.values() for term in terms)
    result = []
    for item in catalog:
        if item["kind"] == "glossary" or item["entity_key"] in viewed_set:
            continue
        item_facets = facets(item)
        preference_matches = item_facets & selected
        reasons = []
        score = 0.0
        if preference_matches:
            score += 1.0
            category = next(
                category for category in categories if item_facets & CATEGORIES[category][1]
            )
            reasons.append(f"В выбранном направлении «{CATEGORIES[category][0]}»")
        for rank, key in enumerate(recent):
            source = by_id[key]
            shared = item_facets & facets(source)
            title_overlap = subjects[key] & subjects[item["entity_key"]]
            # One distinctive subject is useful only with a shared catalog facet;
            # generic actions and legal forms are not evidence of related interests.
            cosine = float(semantic[key][indices[item["entity_key"]]]) if key in semantic else None
            sem_match = cosine is not None and (cosine >= 0.88 or (shared and cosine >= 0.84))
            if len(title_overlap) >= 2 or (shared and title_overlap) or sem_match:
                specificity = sum(
                    math.log(1 + len(catalog) / (1 + frequency[term]))
                    for term in sorted(title_overlap)
                )
                score += (2.0 + min(specificity, 8.0) / 10) / (1 + rank * 0.25)
                if sem_match:
                    score += max(0.0, cosine - 0.75) * 2 / (1 + rank * 0.25)
                reasons.append(
                    f"Связано с материалом, которым вы интересовались: «{source['title']}»"
                )
                break
        if score:
            result.append((score, item["entity_key"], item, reasons))
    result.sort(key=lambda row: (-row[0], row[1]))
    keys = (
        "entity_key",
        "kind",
        "title",
        "description",
        "topics",
        "tags",
        "access_type",
        "canonical_url",
        "data_quality_flags",
    )
    from .promotions import promotion_for

    return [
        {
            "promotion": promotion_for(item),
            **{key: item.get(key) for key in keys},
            "reason": ". ".join(reasons),
            "method": "content_e5_and_facets" if vectors is not None else "lexical_facets",
        }
        for _, _, item, reasons in result[:limit]
    ]


def clarification(query, items, *, needs_context=False):
    from .eligibility import ACTIONS
    from .evidence import subject_terms
    from .query_rules import ANY_NEGATION

    # Non-blocking, only for sparse requests; do not guess around explicit negation.
    if not subject_terms(query) or ANY_NEGATION.search(query):
        return None
    if not needs_context and len(subject_terms(query)) > 2:
        return None
    counts = Counter(topic for item in items[:10] for topic in item.get("topics", []))
    options = [
        topic for topic, count in counts.most_common() if count >= 1 and topic != "Личный опыт"
    ][:3]
    if len(options) < 2:
        materials = [
            item
            for item in items[:10]
            if item.get("kind") != "glossary"
            and item.get("matched_words")
            and len(item["title"]) <= 80
        ][:3]
        core = subject_terms(query) - ACTIONS
        preferred = [
            item
            for item in items[:10]
            if item.get("kind") != "glossary"
            and core & set(tokens(item["title"] + " " + item.get("description", "")))
            and len(item["title"]) <= 80
        ]
        if preferred:
            frequency = Counter(
                term
                for item in preferred
                for term in core & set(tokens(item["title"] + " " + item.get("description", "")))
            )
            rare = {term for term, count in frequency.items() if count == min(frequency.values())}
            materials = [
                item
                for item in preferred
                if rare & set(tokens(item["title"] + " " + item.get("description", "")))
            ][:3]
        if not materials or (len(materials) < 2 and not needs_context):
            return None
        return {
            "question": "С какого шага хотите начать?",
            "options": [
                {"kind": "material", "value": item["entity_key"], "label": item["title"]}
                for item in materials
            ],
        }
    return {
        "question": "Какое направление вам ближе?",
        "options": [{"kind": "topic", "value": topic, "label": topic} for topic in options],
    }
