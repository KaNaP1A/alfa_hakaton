"""Pure domain values shared by API and adapters."""

from dataclasses import dataclass
from enum import StrEnum


class Action(StrEnum):
    IMPRESSION = "impression"
    CLICKED = "clicked"
    VIEWED = "viewed"
    INTERESTED = "interested"
    STARTED = "started"
    COMPLETED = "completed"


@dataclass(frozen=True)
class RecommendationRequest:
    generation: str
    categories: tuple[str, ...]
    viewed: tuple[str, ...]
    completed: tuple[str, ...] = ()
