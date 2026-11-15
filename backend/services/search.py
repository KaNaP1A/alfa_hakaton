from __future__ import annotations

from domain.commands import Kind
from domain.entities import User
from domain.errors import AppError, UpstreamError
from domain.responses import (
    ClarificationOption,
    SearchResponse,
    SuggestResponse,
)
from services.cards import select_cards
from services.model_output import clarification_option, confidence, suggestions
from services.recommendation_context import RecommendationContext
from services.validation import check_generation


class SearchService:
    def __init__(self, model: RecommendationContext) -> None:
        self.model = model

    def suggest(self, q: str, limit: int, user: User) -> SuggestResponse:
        current, allowed, service = self.model.context(user)
        if self.model.upstream:
            payload = service.suggest(q, limit)
            completions = self.model.validate_payload(payload, current, "completions")
            related = self.model.validate_payload(payload, current, "related_topics")
            return {
                "generation": current,
                "completions": suggestions(completions, allowed, current),
                "related_topics": suggestions(related, allowed, current),
                "selection_mode": "selection_id",
            }
        matches = sorted(
            (m for m in allowed.values() if q and q.casefold() in m.title.casefold()),
            key=lambda m: (m.title, m.entity_key),
        )[:limit]
        return {
            "generation": current,
            "completions": [{"label": m.title, "entity_key": m.entity_key} for m in matches],
            "related_topics": [],
            "selection_mode": "replace_query_with_label",
        }

    def search(
        self,
        q: str,
        kind: Kind | None,
        top: int,
        clarification_text: str | None,
        user: User,
        selection_id: str | None = None,
        selection_generation: str | None = None,
        clarification_token: str | None = None,
    ) -> SearchResponse:
        if not q.strip() or any((ord(c) < 32 for c in q)):
            raise AppError(422, "Query must contain text and no control characters")
        current, allowed, service = self.model.context(user)
        if bool(selection_id) != bool(selection_generation):
            raise AppError(422, "selection_id and selection_generation must be supplied together")
        if (clarification_token and clarification_text) or (
            selection_id and (clarification_token or clarification_text)
        ):
            raise AppError(422, "Choose either a suggestion or one clarification")
        if selection_id:
            check_generation(selection_generation, current)
            choices = self.suggest(q, 10, user)
            if not any(
                item.get("id") == selection_id
                for item in choices["completions"] + choices["related_topics"]
            ):
                raise AppError(404, "Suggestion unavailable; request suggestions again")
        if (
            clarification_token
            and clarification_option({"token": clarification_token}, allowed, current) is None
        ):
            raise AppError(409, "Clarification unavailable; repeat search")
        payload = service.search(
            q, 50, kind, clarification_text, selection_id, selection_generation, clarification_token
        )
        items = self.model.validate_payload(payload, current, "results")
        alternatives = payload.get("alternatives", [])
        if not isinstance(alternatives, list) or any(
            (not isinstance(x, dict) for x in alternatives)
        ):
            raise UpstreamError(502, "Invalid recommendation alternatives")
        results = select_cards(items, allowed, top)
        primary_keys = {item["entity_key"] for item in results}
        alternative_cards = select_cards(
            [item for item in alternatives if isinstance(item, dict)],
            {k: v for k, v in allowed.items() if k not in primary_keys},
            top,
        )
        safe_options: list[ClarificationOption] = []
        question = payload.get("clarification")
        if isinstance(question, dict):
            options = question.get("options")
            if isinstance(options, list):
                for option in options:
                    if isinstance(option, dict):
                        safe = clarification_option(option, allowed, current)
                        if safe is not None:
                            safe_options.append(safe)
        return {
            "generation": current,
            "query": q,
            "mode": self.model.mode,
            "results": results,
            "alternatives": alternative_cards,
            "confidence": confidence(payload, bool(results)),
            "clarification": {
                "question": "Уточните вашу задачу",
                "allow_text": True,
                "options": safe_options,
            }
            if payload.get("clarification")
            else None,
            "notice": "Результаты проверены по доступу; список может быть коротким или пустым",
        }
