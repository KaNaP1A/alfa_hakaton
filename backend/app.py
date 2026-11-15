"""Composition root: only wiring, configuration and application lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.errors import install_error_handlers
from api.middleware import install_middleware
from api.routes import router
from config.settings import Settings
from infrastructure.auth import PasswordHasher
from infrastructure.database import connect, initialize
from infrastructure.recommender import DemoRecommender, HttpRecommender
from services.ports import RecommendationPort


def create_app(
    settings: Settings | None = None, recommender: RecommendationPort | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    engine, sessions = connect(settings.database_url)
    upstream = recommender or (HttpRecommender(settings) if settings.reco_mode == "http" else None)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            initialize(engine)
            yield
        finally:
            if upstream:
                upstream.close()
            engine.dispose()

    app = FastAPI(title="Alfa hackathon backend", version="0.2.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.settings = settings
    app.state.upstream = upstream
    app.state.passwords = PasswordHasher()
    app.state.dummy_hash = app.state.passwords.hash("unregistered-account")
    app.state.demo_factory = DemoRecommender
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
