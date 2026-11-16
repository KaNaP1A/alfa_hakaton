"""Composition root: only wiring, configuration and application lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.errors import install_error_handlers
from api.middleware import install_middleware
from api.routes import router
from config.settings import Settings
from domain.ports import DemoFactory, PasswordPort, RecommendationPort, UnitOfWorkFactory
from infrastructure.auth import PasswordHasher
from infrastructure.database import connect, initialize
from infrastructure.python_recommender import PythonRecommender
from infrastructure.recommender import DemoRecommender, HttpRecommender
from infrastructure.uow import SqlAlchemyUnitOfWork
from repositories.unified_catalog import UnifiedCatalog
from services.dependencies import ServiceDependencies


def create_app(
    settings: Settings | None = None,
    recommender: RecommendationPort | None = None,
    uow_factory: UnitOfWorkFactory | None = None,
    passwords: PasswordPort | None = None,
    demo_factory: DemoFactory | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    storage = connect(settings.database_url) if uow_factory is None else None
    engine, sessions = storage if storage is not None else (None, None)
    if uow_factory is None:
        assert sessions is not None
        unified = (
            UnifiedCatalog(Path(settings.unified_catalog)) if settings.unified_catalog else None
        )
        uow_factory = partial(
            SqlAlchemyUnitOfWork,
            sessions,
            catalog_source=settings.catalog_source,
            generation=settings.catalog_generation,
            unified_catalog=unified,
        )
    upstream = recommender
    if upstream is None:
        if settings.reco_mode == "http":
            upstream = HttpRecommender(settings)
        elif settings.reco_mode == "python":
            upstream = PythonRecommender(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            if engine is not None and settings.auto_create_tables:
                initialize(engine)
            yield
        finally:
            if upstream:
                upstream.close()
            if engine is not None:
                engine.dispose()

    app = FastAPI(title="Alfa hackathon backend", version="0.2.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.uow_factory = uow_factory
    app.state.settings = settings
    app.state.upstream = upstream
    password_service = passwords if passwords is not None else PasswordHasher()
    app.state.services = ServiceDependencies(
        uow_factory=uow_factory,
        passwords=password_service,
        recommender=upstream,
        demo_factory=demo_factory if demo_factory is not None else DemoRecommender,
        mode=settings.reco_mode,
        token_ttl=settings.token_ttl,
        dummy_hash=password_service.hash("unregistered-account"),
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "PUT"],
            allow_headers=["Authorization", "Content-Type"],
        )
    install_error_handlers(app)
    install_middleware(app, settings)
    app.include_router(router)
    return app
