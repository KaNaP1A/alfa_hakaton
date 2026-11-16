from dataclasses import fields

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from domain import entities
from domain.commands import ActivityInput, CatalogImport
from domain.errors import RepositoryConflict
from domain.types import JsonObject
from infrastructure.database import Activity, SessionToken, User
from repositories.catalog import generation, history, import_catalog, visible_materials


class SqlAlchemyRepository:
    def __init__(self, db: Session, *, compatible_generations: tuple[str, ...] = ()) -> None:
        self.db = db
        self.compatible_generations = compatible_generations

    def user(self, user_id: str) -> entities.User | None:
        row = self.db.get(User, user_id)
        return entities.User(row.id, row.username, row.password_hash, row.profile) if row else None

    def by_username(self, username: str) -> entities.User | None:
        row = self.db.scalar(select(User).where(User.username == username))
        return self.user(row.id) if row else None

    def authenticated(self, digest: str, now: float) -> entities.User | None:
        row = self.db.get(SessionToken, digest)
        return self.user(row.user_id) if row and row.expires_at > now else None

    def create_user(self, user: entities.User) -> None:
        self.db.add(User(**{f.name: getattr(user, f.name) for f in fields(user)}))
        self.flush("Username already registered")

    def save_token(self, digest: str, user_id: str, expires_at: float) -> None:
        self.db.add(SessionToken(digest=digest, user_id=user_id, expires_at=expires_at))
        self.flush()

    def revoke_token(self, digest: str) -> None:
        self.db.execute(delete(SessionToken).where(SessionToken.digest == digest))
        self.flush()

    def update_profile(self, user_id: str, profile: JsonObject) -> None:
        row = self.db.get(User, user_id)
        if row is not None:
            row.profile = profile
        self.flush()

    def import_catalog(self, data: CatalogImport) -> None:
        import_catalog(self.db, data)

    def generation(self) -> str:
        return generation(self.db)

    def visible_materials(self, user_id: str, current: str) -> dict[str, entities.Material]:
        return {
            key: entities.Material(
                entity_key=row.entity_key,
                generation=row.generation,
                kind=row.kind,
                title=row.title,
                description=row.description,
                topics=row.topics,
                published=row.published,
                access=row.access,
                canonical_url=row.canonical_url,
                price_amount=row.price_amount,
                price_currency=row.price_currency,
            )
            for key, row in visible_materials(self.db, user_id, current).items()
        }

    def history(
        self, user_id: str, current: str, allowed: dict[str, entities.Material]
    ) -> tuple[list[str], list[str]]:
        return history(self.db, user_id, current, allowed, self.compatible_generations)

    def find_event(self, user_id: str, event_id: str) -> entities.Activity | None:
        row = self.db.scalar(
            select(Activity).where(Activity.user_id == user_id, Activity.event_id == event_id)
        )
        return self._activity(row) if row else None

    def add_event(self, user_id: str, data: ActivityInput) -> entities.Activity:
        row = Activity(user_id=user_id, **data.model_dump(), source="self_reported")
        self.db.add(row)
        self.flush("Concurrent event submission; retry")
        return self._activity(row)

    def events(
        self, user_id: str, current: str, allowed: list[str], limit: int
    ) -> list[entities.Activity]:
        rows = self.db.scalars(
            select(Activity)
            .where(
                Activity.user_id == user_id,
                Activity.generation.in_((current, *self.compatible_generations)),
                Activity.entity_key.in_(allowed),
            )
            .order_by(Activity.id.desc())
            .limit(limit)
        )
        return [self._activity(row) for row in rows]

    def _activity(self, row: Activity) -> entities.Activity:
        return entities.Activity(
            **{f.name: getattr(row, f.name) for f in fields(entities.Activity)}
        )

    def flush(self, conflict: str = "Conflicting write") -> None:
        try:
            self.db.flush()
        except IntegrityError as error:
            raise RepositoryConflict(conflict) from error
