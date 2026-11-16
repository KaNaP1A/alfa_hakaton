from __future__ import annotations

from domain.commands import ActivityInput
from domain.entities import User
from domain.errors import AppError
from domain.ports import (
    ActivityRepository,
    TransactionPort,
)
from domain.responses import (
    EventResponse,
    HistoryResponse,
)
from services.catalog import CatalogService
from services.validation import check_generation


class ActivityService:
    def __init__(
        self, repository: ActivityRepository, catalog: CatalogService, transaction: TransactionPort
    ) -> None:
        self.repository = repository
        self.catalog = catalog
        self.transaction = transaction

    def event(self, data: ActivityInput, user: User) -> EventResponse:
        current, allowed = self.catalog.context(user)
        check_generation(data.generation, current)
        if data.entity_key not in allowed:
            raise AppError(404, "Material unavailable")
        if data.action in {"started", "completed"} and allowed[data.entity_key].kind != "course":
            raise AppError(422, "Only courses can be started or completed")
        if data.action in {"started", "completed"} and not allowed[data.entity_key].access_verified:
            raise AppError(403, "Course access is not verified")
        existing = self.repository.find_event(user.id, data.event_id)
        if existing:
            if any((getattr(existing, key) != value for key, value in data.model_dump().items())):
                raise AppError(409, "event_id already used for a different event")
            return {"id": existing.id, "duplicate": True, "source": existing.source}
        activity = self.repository.add_event(user.id, data)
        self.transaction.commit()
        return {"id": activity.id, "duplicate": False, "source": activity.source}

    def events(self, limit: int, user: User) -> HistoryResponse:
        current, allowed = self.catalog.context(user)
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
