from __future__ import annotations

from typing import Literal, overload

from pydantic import TypeAdapter

from domain.commands import GenerationRequest, Profile
from domain.entities import User
from domain.errors import UpstreamError
from domain.ports import (
    ActivityRepository,
    InterestRecommendationPort,
    ProfileRecommendationPort,
)
from domain.responses import (
    PlanResponse,
    PlanStep,
    RecommendationResponse,
)
from domain.types import JsonObject
from services.cards import card, select_cards
from services.commercial_order import prioritize
from services.recommendation_context import RecommendationContext
from services.validation import check_generation


class RecommendationService:
    def __init__(self, model: RecommendationContext, activity: ActivityRepository) -> None:
        self.model = model
        self.repository = activity

    def interests(self, user: User) -> JsonObject:
        current, allowed, service = self.model.context(user)
        if not isinstance(service, InterestRecommendationPort):
            raise UpstreamError(503, "Interest directory is unavailable")
        payload = service.interests()
        check_generation(payload.get("generation"), current)
        categories = payload.get("categories")
        if not isinstance(categories, list):
            raise UpstreamError(502, "Invalid interest directory")
        output: list[object] = []
        labels = {
            "business": "Бизнес",
            "finance": "Финансы",
            "team": "Команда",
            "marketing": "Маркетинг",
            "technology": "Технологии",
        }
        for category in categories:
            if not isinstance(category, dict):
                raise UpstreamError(502, "Invalid interest category")
            identifier, topics = category.get("id"), category.get("topics")
            if (
                not isinstance(identifier, str)
                or identifier not in labels
                or not isinstance(topics, list)
            ):
                raise UpstreamError(502, "Invalid interest category")
            included: list[object] = []
            all_keys: set[str] = set()
            for topic in topics:
                if not isinstance(topic, dict) or not isinstance(topic.get("value"), str):
                    raise UpstreamError(502, "Invalid interest topic")
                value = topic["value"]
                keys = {m.entity_key for m in allowed.values() if value in m.topics}
                if keys:
                    all_keys.update(keys)
                    included.append({"value": value, "label": value, "material_count": len(keys)})
            if included:
                output.append(
                    {
                        "id": identifier,
                        "label": labels[identifier],
                        "material_count": len(all_keys),
                        "topics": included,
                    }
                )
        return TypeAdapter(JsonObject).validate_python(
            {"generation": current, "categories": output}
        )

    @overload
    def personalized(
        self, data: GenerationRequest, user: User, plan: Literal[False]
    ) -> RecommendationResponse: ...

    @overload
    def personalized(
        self, data: GenerationRequest, user: User, plan: Literal[True]
    ) -> PlanResponse: ...

    def personalized(
        self, data: GenerationRequest, user: User, plan: bool
    ) -> RecommendationResponse | PlanResponse:
        current, allowed, service = self.model.context(user)
        check_generation(data.generation, current)
        viewed, completed = self.repository.history(user.id, current, allowed)
        profile = Profile.model_validate(user.profile)
        if self.model.mode == "python" and isinstance(service, ProfileRecommendationPort):
            payload = service.recommend_profile(
                current,
                profile.model_dump(),
                viewed,
                completed,
                plan=plan,
                allowed_keys=set(allowed),
            )
        elif not plan and profile.selected_facets:
            if not isinstance(service, InterestRecommendationPort):
                raise UpstreamError(503, "Interest recommendations are unavailable")
            payload = service.recommend_by_interests(
                current, list(profile.categories), profile.selected_facets, viewed
            )
        else:
            payload = service.recommend(
                current,
                list(profile.categories),
                viewed,
                completed if plan else None,
            )
        items = self.model.validate_payload(payload, current, "steps" if plan else "results")
        if not plan:
            cards = select_cards(prioritize(items, allowed), allowed, 5)
            for item in cards:
                if item["topics"]:
                    item["reason"] = "Темы материала: " + ", ".join(item["topics"][:3])
            return {
                "generation": current,
                "mode": self.model.mode,
                "results": cards,
            }
        keys: list[str] = []
        reasons: dict[str, str] = {}
        for step in items:
            material = step.get("material")
            key = material.get("entity_key") if isinstance(material, dict) else None
            if not isinstance(key, str) or key not in allowed:
                return {
                    "generation": current,
                    "status": "insufficient_evidence",
                    "steps": [],
                    "notice": "Часть маршрута недоступна; требуется пересчёт",
                }
            keys.append(key)
            evidence = step.get("evidence")
            evidence_key = evidence.get("entity_key") if isinstance(evidence, dict) else None
            if isinstance(evidence_key, str) and evidence_key in allowed and evidence_key in viewed:
                source = allowed[evidence_key]
                action = "отметили завершённым" if evidence_key in completed else "просматривали"
                reason = f"Вы {action} материал «{source.title[:150]}»."
                shared = sorted(set(source.topics).intersection(allowed[key].topics))
                if shared:
                    reason += " Общие темы: " + ", ".join(shared[:3]) + "."
                reasons[key] = reason
        safe_steps: list[PlanStep] = []
        seen: set[str] = set()
        for key in keys[:3]:
            if key in seen:
                continue
            seen.add(key)
            safe_steps.append(
                {
                    "number": len(safe_steps) + 1,
                    "material": card(allowed[key]),
                    "action": "study",
                    "why": reasons.get(key, "Тематическая рекомендация по вашей истории"),
                }
            )
        status = payload.get("status", "insufficient_evidence")
        if not isinstance(status, str) or status not in {
            "needs_activity",
            "insufficient_evidence",
            "partial",
            "ready",
            "uncertain",
        }:
            status = "insufficient_evidence"
        if not safe_steps and status in {"ready", "partial"}:
            status = "insufficient_evidence"
        return {
            "generation": current,
            "mode": self.model.mode,
            "status": status,
            "steps": safe_steps,
            "notice": "Тематическая эвристика; история обучения указана пользователем",
        }

    def recommend(self, data: GenerationRequest, user: User) -> RecommendationResponse:
        return self.personalized(data, user, False)

    def plan(self, data: GenerationRequest, user: User) -> PlanResponse:
        return self.personalized(data, user, True)
