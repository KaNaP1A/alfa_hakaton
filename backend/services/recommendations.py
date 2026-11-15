from __future__ import annotations

from typing import Literal, overload

from domain.commands import GenerationRequest, Profile
from domain.entities import User
from domain.ports import (
    ActivityRepository,
)
from domain.responses import (
    PlanResponse,
    PlanStep,
    RecommendationResponse,
)
from services.cards import card, select_cards
from services.recommendation_context import RecommendationContext
from services.validation import check_generation


class RecommendationService:
    def __init__(self, model: RecommendationContext, activity: ActivityRepository) -> None:
        self.model = model
        self.repository = activity

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
        payload = service.recommend(
            current,
            list(Profile.model_validate(user.profile).categories),
            viewed,
            completed if plan else None,
        )
        items = self.model.validate_payload(payload, current, "steps" if plan else "results")
        if not plan:
            return {
                "generation": current,
                "mode": self.model.mode,
                "results": select_cards(items, allowed, 5),
            }
        keys: list[str] = []
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
                    "why": "Тематическая рекомендация по вашей истории",
                }
            )
        status = payload.get("status", "insufficient_evidence")
        if not isinstance(status, str) or status not in {
            "needs_activity",
            "insufficient_evidence",
            "partial",
            "ready",
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
