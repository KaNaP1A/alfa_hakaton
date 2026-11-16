"""Public response contracts shared by services and HTTP serialization."""

from typing import Literal

from typing_extensions import NotRequired, TypedDict

from domain.types import JsonObject


class Price(TypedDict):
    status: Literal["known", "unknown", "conditional"]
    amount: str | None
    currency: str | None


class MaterialCard(TypedDict):
    entity_key: str
    generation: str
    kind: str
    title: str
    description: str
    topics: list[str]
    canonical_url: str | None
    access_type: str
    access_verified: bool
    price: Price
    source_url: NotRequired[str | None]
    reason: NotRequired[str]


class TokenResponse(TypedDict):
    access_token: str
    token_type: str
    expires_in: int


class HealthResponse(TypedDict):
    status: str
    mode: str
    generation: str
    demo: NotRequired[bool]
    note: NotRequired[str]


class UserResponse(TypedDict):
    id: str
    username: str
    profile: JsonObject


class EventResponse(TypedDict):
    id: int
    duplicate: bool
    source: str


class HistoryItem(TypedDict):
    event_id: str
    entity_key: str
    action: str
    position: int | None
    created_at: float
    source: str


class HistoryResponse(TypedDict):
    generation: str
    items: list[HistoryItem]


class CatalogResponse(TypedDict):
    generation: str
    items: list[MaterialCard]
    total: int


class Completion(TypedDict):
    label: str
    entity_key: str
    id: NotRequired[str]
    selection_generation: NotRequired[str]
    kind: NotRequired[str]


class SuggestResponse(TypedDict):
    generation: str
    completions: list[Completion]
    related_topics: list[Completion]
    selection_mode: str


class ClarificationOption(TypedDict):
    label: str
    kind: str
    token: str


class Confidence(TypedDict):
    status: str
    reason: NotRequired[str]


class Clarification(TypedDict):
    question: str
    allow_text: bool
    options: NotRequired[list[ClarificationOption]]


class SearchResponse(TypedDict):
    generation: str
    query: str
    mode: str
    results: list[MaterialCard]
    alternatives: list[MaterialCard]
    confidence: Confidence
    clarification: Clarification | None
    notice: str


class RecommendationResponse(TypedDict):
    generation: str
    mode: str
    results: list[MaterialCard]


class PlanStep(TypedDict):
    number: int
    material: MaterialCard
    action: str
    why: str


class PlanResponse(TypedDict):
    generation: str
    mode: NotRequired[str]
    status: str
    steps: list[PlanStep]
    notice: str
