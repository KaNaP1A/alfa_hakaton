from __future__ import annotations

import time
from collections.abc import Mapping

from sqlalchemy import Select, delete, or_, select
from sqlalchemy.orm import Session

from domain.errors import AppError
from infrastructure.database import Activity, CatalogState, Grant, Material
from schemas.requests import CatalogImport


class CatalogUnavailable(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(503, message)


def generation(db: Session) -> str:
    state = db.get(CatalogState, 1)
    if state is None:
        raise CatalogUnavailable("Import the trusted catalog before using recommendations")
    return state.generation


def import_catalog(db: Session, data: CatalogImport) -> None:
    db.execute(delete(Material))
    for item in data.materials:
        db.add(Material(generation=data.generation, **item.model_dump()))
    state = db.get(CatalogState, 1)
    if state is None:
        db.add(CatalogState(id=1, generation=data.generation))
    else:
        state.generation = data.generation
    db.flush()


def visible_query(user_id: str, current: str) -> Select[tuple[Material]]:
    grants = select(Grant.entity_key).where(
        Grant.user_id == user_id, or_(Grant.expires_at.is_(None), Grant.expires_at > time.time())
    )
    return select(Material).where(
        Material.generation == current,
        Material.published.is_(True),
        or_(Material.access == "public", Material.entity_key.in_(grants)),
    )


def visible_materials(db: Session, user_id: str, current: str) -> dict[str, Material]:
    return {item.entity_key: item for item in db.scalars(visible_query(user_id, current))}


def history(
    db: Session, user_id: str, current: str, allowed: Mapping[str, object]
) -> tuple[list[str], list[str]]:
    rows = db.scalars(
        select(Activity)
        .where(Activity.user_id == user_id, Activity.generation == current)
        .order_by(Activity.id.desc())
        .limit(1000)
    )
    viewed, completed, seen = ([], [], set())
    for row in rows:
        if row.entity_key not in allowed or row.entity_key in seen:
            continue
        if row.action in {"viewed", "interested", "started", "completed"}:
            seen.add(row.entity_key)
            viewed.append(row.entity_key)
        if len(seen) == 50:
            break
    if seen:
        completed = list(
            db.scalars(
                select(Activity.entity_key)
                .where(
                    Activity.user_id == user_id,
                    Activity.generation == current,
                    Activity.entity_key.in_(seen),
                    Activity.action == "completed",
                )
                .distinct()
            )
        )
    return (list(reversed(viewed)), completed)
