"""In-process adapter for the unmodified alfa_reco library."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from threading import RLock
from typing import Any, ClassVar

from pydantic import TypeAdapter

from config.settings import Settings
from domain.errors import UpstreamError
from domain.types import JsonObject


class PythonRecommender:
    """One model per process, including across multiple application instances.

    Publish the singleton only after successful initialization. Serialize inference
    because SearchEngine also maintains mutable caches. Workers have separate models.
    """

    catalog: Path
    _inference_lock: RLock
    _engine: Any  # External alfa_reco library has no type annotations.

    _instance: ClassVar[PythonRecommender | None] = None
    _load_lock: ClassVar[RLock] = RLock()

    def __new__(cls, settings: Settings) -> PythonRecommender:
        catalog = Path(settings.reco_catalog).expanduser().resolve()
        with cls._load_lock:
            if cls._instance is not None:
                if cls._instance.catalog != catalog:
                    raise ValueError("Python ML singleton already uses a different catalog")
                return cls._instance
            instance = super().__new__(cls)
            instance.catalog = catalog
            instance._inference_lock = RLock()
            # Install alfa_reco in the backend environment; no subprocess or HTTP.
            engine_type = import_module("alfa_reco.search").SearchEngine
            instance._engine = engine_type(catalog, semantic=False, llm_enabled=False)
            instance._engine.relevance_backend()  # Eagerly load E5 and CatBoost once.
            cls._instance = instance
            return instance

    def __init__(self, settings: Settings) -> None:
        # All initialization is guarded by _load_lock in __new__.
        pass

    def close(self) -> None:
        # The singleton lives for the process lifetime and may serve other apps.
        pass

    def _call(self, operation: Callable[[], object]) -> JsonObject:
        with self._inference_lock:
            try:
                result = operation()
            except (ValueError, TypeError) as error:
                raise UpstreamError(
                    400, "Algorithm rejected the request; refresh and try again"
                ) from error
            except Exception as error:
                raise UpstreamError(502, "Python recommendation model failed") from error
            return TypeAdapter(JsonObject).validate_python(result)

    def health(self) -> JsonObject:
        return {
            "status": "ok",
            "generation": self._engine.generation,
            "default_search_mode": "relevance",
            "relevance_available": True,
        }

    def search(
        self,
        q: str,
        top: int,
        kind: str | None = None,
        clarification_text: str | None = None,
        selection_id: str | None = None,
        selection_generation: str | None = None,
        clarification_token: str | None = None,
    ) -> JsonObject:
        return self._call(
            lambda: self._engine.search(
                q,
                mode="relevance",
                top=top,
                kind=kind,
                clarification_text=clarification_text,
                selection_id=selection_id,
                selection_generation=selection_generation,
                clarification_token=clarification_token,
            )
        )

    def suggest(self, q: str, limit: int) -> JsonObject:
        return self._call(lambda: self._engine.suggest(q, limit))

    def recommend(
        self,
        generation: str,
        categories: list[str],
        viewed: list[str],
        completed: list[str] | None = None,
    ) -> JsonObject:
        def run() -> object:
            if generation != self._engine.generation:
                raise ValueError("Catalog changed; refresh local profile")
            vectors = self._engine.relevance_backend().vectors["card"]
            if completed is not None:
                plan = import_module("alfa_reco.development_plan").development_plan
                return {
                    "generation": generation,
                    **plan(self._engine.catalog, categories, viewed, completed, vectors=vectors),
                }
            recommend = import_module("alfa_reco.personalization").recommend
            return {
                "generation": generation,
                "results": recommend(self._engine.catalog, categories, viewed, vectors=vectors),
            }

        return self._call(run)
