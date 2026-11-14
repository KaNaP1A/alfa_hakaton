"""Optional profile-aware recommendations and plans for backend integration.

Signals and weights are explicit heuristics, not estimates of learning or conversion.
"""

from .development_plan import development_plan
from .eligibility import USER_KINDS
from .personalization import CATEGORIES, facets, recommend
from .profile_metadata import (
    EXPERIENCE,
    STAGES,
    experience_evidence,
    industry_matches,
    stage_evidence,
)
from .suggestions import validate_query

SIGNAL_WEIGHT = {"viewed": 1.0, "interested": 1.5, "started": 2.0, "completed": 3.0}
PROFILE_FIELDS = frozenset(
    {"generation", "goal", "business_stage", "industry", "experience", "preferred_kinds", "categories", "events", "allow_revisit", "clarification_token", "clarification_text", "region", "focus_facet"}
)


def validate_profile(engine, profile):
    if not isinstance(profile, dict) or set(profile) - PROFILE_FIELDS:
        raise ValueError("Unknown or invalid profile fields")
    if profile.get("generation") != engine.generation:
        raise ValueError("Profile generation does not match catalog")
    goal = profile.get("goal")
    if goal is not None:
        validate_query(goal)
        if not goal.strip():
            raise ValueError("Goal must not be empty")
        goal = goal.strip()
    token, clarification = profile.get("clarification_token"), profile.get("clarification_text")
    if token is not None and (not isinstance(token, str) or not token or len(token) > 2048):
        raise ValueError("Invalid clarification token")
    if clarification is not None:
        validate_query(clarification)
        if not clarification.strip() or len(clarification) > 100:
            raise ValueError("Invalid clarification text")
        clarification = clarification.strip()
    if token is not None and clarification is not None:
        raise ValueError("Choose either a clarification option or text")
    if (token is not None or clarification is not None) and not goal:
        raise ValueError("Clarification requires a goal")
    allow_revisit = profile.get("allow_revisit", False)
    if type(allow_revisit) is not bool:
        raise ValueError("allow_revisit must be a boolean")
    stage, experience = profile.get("business_stage"), profile.get("experience")
    if stage is not None and (not isinstance(stage, str) or stage not in STAGES):
        raise ValueError("Unknown business stage")
    if experience is not None and (not isinstance(experience, str) or experience not in EXPERIENCE):
        raise ValueError("Unknown experience level")
    industry = profile.get("industry")
    if industry is not None:
        if not isinstance(industry, str) or not industry.strip() or len(industry) > 150:
            raise ValueError("Invalid industry")
        validate_query(industry)
        industry = industry.strip()
    region = profile.get("region")
    if region is not None:
        if not isinstance(region, str) or not region.strip() or len(region) > 150:
            raise ValueError("Invalid region")
        validate_query(region)
        region = region.strip()
    categories = profile.get("categories", [])
    if not isinstance(categories, list) or len(categories) > len(CATEGORIES) or any(
        not isinstance(value, str) or value not in CATEGORIES for value in categories
    ):
        raise ValueError("Invalid interest categories")
    preferred = profile.get("preferred_kinds", [])
    if not isinstance(preferred, list) or len(preferred) > len(USER_KINDS) or any(
        not isinstance(value, str) or value not in USER_KINDS for value in preferred
    ):
        raise ValueError("Invalid preferred material types")
    focus = profile.get("focus_facet")
    if focus is not None:
        if not isinstance(focus, str) or not focus.strip() or len(focus) > 150 or not categories:
            raise ValueError("A focus facet requires selected categories")
        validate_query(focus)
        from .cold_start import category_facets

        allowed = {label for category in categories for label in category_facets(category)}
        matches = [label for label in allowed if label.casefold() == focus.strip().casefold()]
        if len(matches) != 1 or not any(
            item.get("kind") in USER_KINDS and matches[0] in facets(item) for item in engine.catalog
        ):
            raise ValueError("Focus facet is unavailable for selected categories")
        focus = matches[0]
    events = profile.get("events", [])
    if not isinstance(events, list) or len(events) > 50:
        raise ValueError("Events must be a list of at most 50 entries")
    catalog = {item["entity_key"]: item for item in engine.catalog}
    if len(catalog) != len(engine.catalog):
        raise ValueError("Duplicate catalog entity keys")
    strongest = {}
    for position, event in enumerate(events):
        if not isinstance(event, dict) or set(event) != {"entity_key", "action"}:
            raise ValueError("Each event needs entity_key and action")
        key, action = event["entity_key"], event["action"]
        if not isinstance(key, str) or key not in catalog or catalog[key]["kind"] not in USER_KINDS:
            raise ValueError("Event item is not in the catalog")
        if not isinstance(action, str) or action not in SIGNAL_WEIGHT:
            raise ValueError("Unknown activity action")
        if action in {"started", "completed"} and catalog[key]["kind"] != "course":
            raise ValueError("Only courses can be started or completed")
        previous = strongest.get(key)
        if previous is None or SIGNAL_WEIGHT[action] > SIGNAL_WEIGHT[previous["action"]]:
            strongest[key] = {"entity_key": key, "action": action, "position": position}
        else:
            # Repeated events do not increase strength; ordering uses the latest occurrence.
            previous["position"] = position
    ordered = sorted(strongest.values(), key=lambda x: -x["position"])
    return {
        "goal": goal,
        "business_stage": stage,
        "industry": industry,
        "region": region,
        "focus_facet": focus,
        "experience": experience,
        "categories": list(dict.fromkeys(categories)),
        "preferred_kinds": list(dict.fromkeys(preferred)),
        "events": ordered,
        "allow_revisit": allow_revisit,
        "clarification_token": token,
        "clarification_text": clarification,
    }


def _profile_usage(profile, catalog):
    industry = profile["industry"]
    industry_known = bool(industry and any(industry_matches(industry, item) for item in catalog))
    stage_known = bool(profile["business_stage"] and any(
        stage_evidence(profile["business_stage"], item) for item in catalog
    ))
    experience_known = bool(profile["experience"] and any(
        experience_evidence(profile["experience"], item) for item in catalog
    ))
    return {
        "goal": "used" if profile["goal"] else "not_provided",
        "categories": "used" if profile["categories"] else "not_provided",
        "events": "used" if profile["events"] else "not_provided",
        "preferred_kinds": "used_when_matched" if profile["preferred_kinds"] else "not_provided",
        "industry": ("used_when_matched" if industry_known else "no_catalog_match")
        if industry else "not_provided",
        "business_stage": ("used_when_source_matched" if stage_known else "no_catalog_match")
        if profile["business_stage"] else "not_provided",
        "experience": ("used_when_source_matched" if experience_known else "no_catalog_match")
        if profile["experience"] else "not_provided",
        "allow_revisit": profile["allow_revisit"],
        "region": ("cold_start_possible_mentions_only" if not profile["goal"] and not profile["events"]
                   else "not_used_for_goal_or_history") if profile["region"] else "not_provided",
        "focus_facet": "strict_catalog_facet_filter" if profile["focus_facet"] else "not_provided",
    }


def _goal_search(engine, profile):
    kwargs = {}
    if profile["clarification_token"] is not None:
        kwargs["clarification_token"] = profile["clarification_token"]
    if profile["clarification_text"] is not None:
        kwargs["clarification_text"] = profile["clarification_text"]
    result = engine.search(profile["goal"], mode="relevance", top=50, **kwargs)
    if not isinstance(result, dict) or not isinstance(result.get("results"), list):
        raise ValueError("Search returned invalid results")
    catalog = {item["entity_key"]: item for item in engine.catalog}
    seen = set()
    for item in result["results"]:
        key = item.get("entity_key") if isinstance(item, dict) else None
        if not isinstance(key, str) or key not in catalog or catalog[key]["kind"] not in USER_KINDS or key in seen:
            raise ValueError("Search returned unknown or duplicate material")
        seen.add(key)
    if not isinstance(result.get("alternatives", []), list):
        raise ValueError("Search returned invalid alternatives")
    for item in result.get("alternatives", []):
        key = item.get("entity_key") if isinstance(item, dict) else None
        if not isinstance(key, str) or key not in catalog or catalog[key]["kind"] not in USER_KINDS:
            raise ValueError("Search returned unknown alternative")
    return result


def _search_context(search, excluded):
    if search is None:
        return None
    return {
        "confidence": search.get("confidence"),
        "clarification": search.get("clarification"),
        "focus": search.get("focus"),
        "coverage": search.get("coverage"),
        "query_rules": search.get("query_rules"),
        "request_understanding": search.get("request_understanding"),
        "retrieval_diagnostics": search.get("retrieval_diagnostics"),
        "alternatives": [item for item in search.get("alternatives", []) if not excluded(item["entity_key"])],
        "notice": search.get("notice"),
    }


def _uncertain(search):
    if search is None:
        return False
    rules = search.get("query_rules")
    if isinstance(rules, dict) and (
        rules.get("unsupported_constraints") or rules.get("unresolved_negation")
    ):
        return True
    confidence = search.get("confidence")
    return not isinstance(confidence, dict) or confidence.get("status") in {None, "uncertain"}


def recommend_for_profile(engine, profile, *, limit=5, vectors=None):
    """Use the goal as the candidate boundary; enrich existing candidates only."""
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Limit must be an integer between 1 and 20")
    profile = validate_profile(engine, profile)
    catalog = {item["entity_key"]: item for item in engine.catalog}
    usage = _profile_usage(profile, engine.catalog)
    if not profile["goal"] and not profile["events"]:
        from .cold_start import recommend_cold_start

        results, onboarding = recommend_cold_start(engine.catalog, profile, limit)
        return {
            "generation": engine.generation,
            "method": "cold_start_facets_v1",
            "status": "ready" if results else "insufficient_evidence",
            "profile_usage": usage,
            "goal_search": None,
            "onboarding": onboarding,
            "results": results,
            "notice": "Подбор основан на выбранных направлениях и метаданных снимка, а не на популярности или подтверждённой полезности.",
        }
    history = {}
    for position, event in enumerate(profile["events"][:20]):
        matches = recommend(engine.catalog, [], [event["entity_key"]], limit=20, vectors=vectors)
        for rank, item in enumerate(matches, 1):
            key = item["entity_key"]
            affinity = SIGNAL_WEIGHT[event["action"]] / 3 / (1 + position * 0.15) / (1 + (rank - 1) * 0.1)
            if key not in history or affinity > history[key]["strength"]:
                history[key] = {"strength": affinity, "entity_key": event["entity_key"], "action": event["action"], "item": item}
    candidates = {}
    search = None
    if profile["goal"]:
        search = _goal_search(engine, profile)
        for rank, item in enumerate(search["results"], 1):
            key = item.get("entity_key")
            candidates[key] = {"item": item, "base": 1 / (10 + rank), "rank": rank}
    else:
        for key, signal in history.items():
            # Reuse the existing content recommendation, not a new ungrounded catalog source.
            candidates[key] = {"item": signal["item"], "base": signal["strength"] / 10, "rank": None}
        if profile["categories"]:
            for rank, item in enumerate(recommend(engine.catalog, profile["categories"], [], limit=20, vectors=vectors), 1):
                key = item["entity_key"]
                prior = candidates.setdefault(key, {"item": item, "base": 0.0, "rank": None})
                prior["base"] = max(prior["base"], 0.5 / (10 + rank))
                prior["item"] = prior["item"] or item
    active = {event["entity_key"] for event in profile["events"] if event["action"] in {"started", "completed"}}
    def excluded(key):
        return not profile["allow_revisit"] and key in active
    selected_facets = {name for category in profile["categories"] for name in CATEGORIES[category][1]}
    ranked = []
    for key, candidate in candidates.items():
        if excluded(key):
            continue
        item = catalog[key]
        if profile["focus_facet"] and profile["focus_facet"] not in facets(item):
            continue
        kind_match = item["kind"] in profile["preferred_kinds"]
        industry_match = industry_matches(profile["industry"], item)
        experience_match = experience_evidence(profile["experience"], item)
        stage_match = stage_evidence(profile["business_stage"], item)
        category_match = bool(facets(item) & selected_facets)
        signal = history.get(key)
        score = candidate["base"] * (1.1 if kind_match else 1) * (1.1 if industry_match else 1)
        score *= 1.1 if category_match else 1
        score *= 1.05 if experience_match else 1
        score *= 1.05 if stage_match else 1
        if signal and profile["goal"]:
            score *= 1 + 0.15 * signal["strength"]
        result = dict(candidate["item"] or {
            field: item.get(field) for field in (
                "entity_key", "kind", "title", "description", "topics", "tags", "industries",
                "access_type", "canonical_url", "data_quality_flags",
            )
        })
        result.setdefault("industries", item.get("industries", []))
        result["profile_evidence"] = {
            "goal_rank": candidate["rank"], "preferred_kind": kind_match,
            "industry": industry_match, "category": category_match,
            "activity": {k: signal[k] for k in ("entity_key", "action")} if signal else None,
            "experience": experience_match, "business_stage": stage_match,
        }
        ranked.append((score, key, result))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return {
        "generation": engine.generation,
        "method": "profile_relevance_v1" if profile["goal"] else "profile_activity_facets_v1",
        "status": ("uncertain" if _uncertain(search) else "ready") if ranked else "insufficient_evidence",
        "profile_usage": usage,
        "goal_search": _search_context(search, excluded),
        "results": [item for _, _, item in ranked[:limit]],
        "notice": "Профиль уточняет подборку; оценки и коэффициенты не являются вероятностью полезности.",
    }


def development_plan_for_profile(engine, profile, *, vectors=None):
    """Build an activity-grounded plan, optionally restricted to goal-search candidates."""
    profile = validate_profile(engine, profile)
    groups = {action: [] for action in SIGNAL_WEIGHT}
    for event in reversed(profile["events"]):
        groups[event["action"]].append(event["entity_key"])
    goal_keys, search = None, None
    if profile["goal"]:
        search = _goal_search(engine, profile)
        goal_keys = {item["entity_key"] for item in search["results"]}
    if profile["focus_facet"]:
        facet_keys = {item["entity_key"] for item in engine.catalog if profile["focus_facet"] in facets(item)}
        goal_keys = facet_keys if goal_keys is None else goal_keys & facet_keys
    plan = development_plan(
        engine.catalog, profile["categories"], groups["viewed"], groups["completed"],
        vectors=vectors, started=groups["started"], interested=groups["interested"],
        goal_candidate_keys=goal_keys, preferred_kinds=profile["preferred_kinds"], industry=profile["industry"],
        business_stage=profile["business_stage"], experience=profile["experience"], dedupe_titles=False,
    )
    active = {event["entity_key"] for event in profile["events"]}
    context = _search_context(search, lambda key: key in active)
    if plan["steps"] and _uncertain(search):
        plan["plan_status"] = plan["status"]
        plan["status"] = "uncertain"
    return {"generation": engine.generation, "profile_usage": _profile_usage(profile, engine.catalog), "goal_search": context, **plan}
