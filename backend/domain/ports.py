"""Inner-layer contracts implemented by infrastructure adapters."""

from types import TracebackType
from typing import Protocol, Self, runtime_checkable

from domain import entities
from domain.commands import ActivityInput, CatalogImport
from domain.types import JsonObject


class UserRepository(Protocol):
    """Domain users and sessions; writes stay pending until transaction commit."""

    def user(self, user_id: str) -> entities.User | None: ...
    def by_username(self, username: str) -> entities.User | None: ...
    def authenticated(self, digest: str, now: float) -> entities.User | None: ...
    def create_user(self, user: entities.User) -> None: ...
    def save_token(self, digest: str, user_id: str, expires_at: float) -> None: ...
    def revoke_token(self, digest: str) -> None: ...
    def update_profile(self, user_id: str, profile: JsonObject) -> None: ...


class CatalogRepository(Protocol):
    """Catalog snapshots and authoritative visibility for a user and generation."""

    def import_catalog(self, data: CatalogImport) -> None: ...
    def generation(self) -> str: ...
    def visible_materials(self, user_id: str, current: str) -> dict[str, entities.Material]: ...


class ActivityRepository(Protocol):
    """User activity; history and events are restricted to the supplied visible keys."""

    def history(
        self, user_id: str, current: str, allowed: dict[str, entities.Material]
    ) -> tuple[list[str], list[str]]: ...
    def find_event(self, user_id: str, event_id: str) -> entities.Activity | None: ...
    def add_event(self, user_id: str, data: ActivityInput) -> entities.Activity: ...
    def events(
        self, user_id: str, current: str, allowed: list[str], limit: int
    ) -> list[entities.Activity]: ...


class RecommendationPort(Protocol):
    def health(self) -> JsonObject: ...
    def search(
        self,
        q: str,
        top: int,
        kind: str | None = None,
        clarification_text: str | None = None,
        selection_id: str | None = None,
        selection_generation: str | None = None,
        clarification_token: str | None = None,
    ) -> JsonObject: ...
    def suggest(self, q: str, limit: int) -> JsonObject: ...
    def recommend(
        self,
        generation: str,
        categories: list[str],
        viewed: list[str],
        completed: list[str] | None = None,
    ) -> JsonObject: ...
    def close(self) -> None: ...


@runtime_checkable
class InterestRecommendationPort(Protocol):
    """Optional adapter capability for catalog-backed multi-topic selection."""

    def interests(self) -> JsonObject: ...
    def recommend_by_interests(
        self, generation: str, categories: list[str], facets: list[str], viewed: list[str]
    ) -> JsonObject: ...


@runtime_checkable
class ProfileRecommendationPort(Protocol):
    """Optional adapter capability for goal, profile and activity-aware ranking."""

    def recommend_profile(
        self,
        generation: str,
        profile: JsonObject,
        viewed: list[str],
        completed: list[str],
        *,
        plan: bool = False,
        allowed_keys: set[str] | None = None,
    ) -> JsonObject: ...


class PasswordPort(Protocol):
    def hash(self, password: str) -> str: ...
    def matches(self, password: str, encoded: str) -> bool: ...


class DemoFactory(Protocol):
    def __call__(
        self, materials: list[entities.Material], generation: str
    ) -> RecommendationPort: ...


class UnitOfWorkPort(Protocol):
    """One atomic transaction shared by all repositories; rollback/close on exit."""

    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
    @property
    def users(self) -> UserRepository: ...
    @property
    def catalog(self) -> CatalogRepository: ...
    @property
    def activity(self) -> ActivityRepository: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class TransactionPort(Protocol):
    """Services commit an operation; the enclosing unit of work rolls back on failure."""

    def commit(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWorkPort: ...
