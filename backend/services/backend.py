from __future__ import annotations

import secrets
import time
import uuid
from typing import Literal, overload

from config.settings import Settings
from domain.entities import Material, User
from domain.errors import AppError
from domain.errors import AppError as UpstreamError
from domain.responses import (
    CatalogResponse,
    ClarificationOption,
    EventResponse,
    HealthResponse,
    HistoryResponse,
    PlanResponse,
    PlanStep,
    RecommendationResponse,
    SearchResponse,
    SuggestResponse,
    TokenResponse,
    UserResponse,
)
from domain.security import token_digest
from domain.types import JsonObject, JsonValue
from schemas.requests import ActivityInput, Credentials, GenerationRequest, Kind, Profile
from services.cards import card, select_cards
from services.model_output import clarification_option, confidence, suggestions
from services.ports import DemoFactory, PasswordPort, RecommendationPort, UnitOfWorkPort


class BackendService:
    def __init__(
        self,
        uow: UnitOfWorkPort,
        upstream: RecommendationPort | None,
        passwords: PasswordPort,
        demo_factory: DemoFactory,
        settings: Settings,
        dummy_hash: str,
    ) -> None:
        self.uow = uow
        self.repository = uow.repository
        self.upstream = upstream
        self.passwords = passwords
        self.demo_factory = demo_factory
        self.settings = settings
        self.dummy_hash = dummy_hash

    def authenticate(self, token: str | None) -> User:
        user = self.repository.authenticated(token_digest(token), time.time()) if token else None
        if user is None:
            raise AppError(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
        return user

    def issue_token(self, user_id: str) -> TokenResponse:
        token = secrets.token_urlsafe(32)
        self.repository.save_token(
            token_digest(token), user_id, time.time() + self.settings.token_ttl
        )
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": self.settings.token_ttl,
        }

    def context(self, user: User) -> tuple[str, dict[str, Material], RecommendationPort]:
        current = self.repository.generation()
        allowed = self.repository.visible_materials(user.id, current)
        service = self.upstream or self.demo_factory(list(allowed.values()), current)
        return (current, allowed, service)

    def check_generation(self, actual: JsonValue, expected: str) -> None:
        if actual != expected:
            raise AppError(409, "Catalog generation changed; refresh catalog and retry")

    def validate_payload(self, payload: JsonObject, current: str, field: str) -> list[JsonObject]:
        values = payload.get(field)
        if not isinstance(values, list):
            raise UpstreamError(502, "Invalid recommendation response")
        self.check_generation(payload.get("generation"), current)
        result: list[JsonObject] = []
        for value in values:
            if not isinstance(value, dict):
                raise UpstreamError(502, "Invalid recommendation items")
            result.append(value)
        return result

    def health(self) -> HealthResponse:
        return {
            "status": "ok",
            "mode": self.settings.reco_mode,
            "demo": self.settings.reco_mode == "demo",
            "generation": self.repository.generation(),
        }

    def ready(self) -> HealthResponse:
        current = self.repository.generation()
        if self.upstream:
            state = self.upstream.health()
            if state.get("status") != "ok":
                raise UpstreamError(503, "Algorithm is not ready")
            self.check_generation(state.get("generation"), current)
            if (
                self.settings.reco_mode == "http"
                and state.get("default_search_mode") != "relevance"
            ):
                raise UpstreamError(503, "Algorithm must use relevance mode")
            if state.get("relevance_available") is False or (
                self.settings.reco_mode == "http" and state.get("relevance_available") is not True
            ):
                raise UpstreamError(503, "Relevance artifacts unavailable")
        return {
            "status": "ready",
            "mode": self.settings.reco_mode,
            "generation": current,
            "note": "Readiness does not replace a real search smoke test",
        }

    def register(self, data: Credentials) -> TokenResponse:
        user = User(
            id=str(uuid.uuid4()),
            username=data.username,
            password_hash=self.passwords.hash(data.password),
            profile={},
        )
        self.repository.create_user(user)
        result = self.issue_token(user.id)
        self.uow.commit()
        return result

    def login(self, data: Credentials) -> TokenResponse:
        user = self.repository.by_username(data.username)
        encoded = user.password_hash if user else self.dummy_hash
        valid = self.passwords.matches(data.password, encoded)
        if user is None or not valid:
            raise AppError(401, "Invalid username or password")
        result = self.issue_token(user.id)
        self.uow.commit()
        return result

    def logout(self, token: str) -> None:
        self.repository.revoke_token(token_digest(token))
        self.uow.commit()

    def me(self, user: User) -> UserResponse:
        return {"id": user.id, "username": user.username, "profile": user.profile}

    def update_profile(self, data: Profile, user: User) -> Profile:
        user.profile = data.model_dump()
        self.repository.update_profile(user.id, user.profile)
        self.uow.commit()
        return data

    def event(self, data: ActivityInput, user: User) -> EventResponse:
        current, allowed, _ = self.context(user)
        self.check_generation(data.generation, current)
        if data.entity_key not in allowed:
            raise AppError(404, "Material unavailable")
        if data.action in {"started", "completed"} and allowed[data.entity_key].kind != "course":
            raise AppError(422, "Only courses can be started or completed")
        existing = self.repository.find_event(user.id, data.event_id)
        if existing:
            if any((getattr(existing, key) != value for key, value in data.model_dump().items())):
                raise AppError(409, "event_id already used for a different event")
            return {"id": existing.id, "duplicate": True, "source": existing.source}
        activity = self.repository.add_event(user.id, data)
        self.uow.commit()
        return {"id": activity.id, "duplicate": False, "source": activity.source}

    def events(self, limit: int, user: User) -> HistoryResponse:
        current, allowed, _ = self.context(user)
        rows = self.repository.events(user.id, current, list(allowed), limit)
        return {
            "generation": current,
            "items": [
                {
                    "event_id": r.event_id,
                    "entity_key": r.entity_key,
                    "action": r.action,
                    "position": r.position,
                    "created_at": r.created_at,
                    "source": r.source,
                }
                for r in rows
            ],
        }

    def catalog(
        self, q: str, kind: Kind | None, limit: int, offset: int, user: User
    ) -> CatalogResponse:
        current, allowed, _ = self.context(user)
        matches = [
            m
            for m in allowed.values()
            if q.casefold() in m.title.casefold() and (kind is None or m.kind == kind)
        ]
        matches.sort(key=lambda m: (m.title, m.entity_key))
        return {
            "generation": current,
            "items": [card(m) for m in matches[offset : offset + limit]],
            "total": len(matches),
        }

    def suggest(self, q: str, limit: int, user: User) -> SuggestResponse:
        current, allowed, service = self.context(user)
        if self.upstream:
            payload = service.suggest(q, limit)
            completions = self.validate_payload(payload, current, "completions")
            related = self.validate_payload(payload, current, "related_topics")
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
        current, allowed, service = self.context(user)
        if bool(selection_id) != bool(selection_generation):
            raise AppError(422, "selection_id and selection_generation must be supplied together")
        if (clarification_token and clarification_text) or (
            selection_id and (clarification_token or clarification_text)
        ):
            raise AppError(422, "Choose either a suggestion or one clarification")
        if selection_id:
            self.check_generation(selection_generation, current)
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
        items = self.validate_payload(payload, current, "results")
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
            "mode": self.settings.reco_mode,
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
        current, allowed, service = self.context(user)
        self.check_generation(data.generation, current)
        viewed, completed = self.repository.history(user.id, current, allowed)
        payload = service.recommend(
            current,
            list(Profile.model_validate(user.profile).categories),
            viewed,
            completed if plan else None,
        )
        items = self.validate_payload(payload, current, "steps" if plan else "results")
        if not plan:
            return {
                "generation": current,
                "mode": self.settings.reco_mode,
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
            "mode": self.settings.reco_mode,
            "status": status,
            "steps": safe_steps,
            "notice": "Тематическая эвристика; история обучения указана пользователем",
        }

    def recommend(self, data: GenerationRequest, user: User) -> RecommendationResponse:
        return self.personalized(data, user, False)

    def plan(self, data: GenerationRequest, user: User) -> PlanResponse:
        return self.personalized(data, user, True)
