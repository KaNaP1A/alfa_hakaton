import logging
import threading
import time
import uuid
from collections import OrderedDict, deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .auth import issue_token, password_hash, password_matches, token_digest
from .catalog import (
    CatalogUnavailable,
    card,
    enrich,
    generation,
    history,
    visible_materials,
)
from .config import Settings
from .database import Activity, SessionToken, User, connect, initialize
from .recommender import DemoRecommender, HttpRecommender, UpstreamError
from .schemas import ActivityInput, Credentials, GenerationRequest, Kind, Profile

bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger("uvicorn.error")


def create_app(settings=None, recommender=None):
    settings = settings or Settings.from_env()
    engine, sessions = connect(settings.database_url)
    upstream = recommender or (HttpRecommender(settings) if settings.reco_mode == "http" else None)

    @asynccontextmanager
    async def lifespan(app):
        initialize(engine)
        yield
        if upstream:
            upstream.close()
        engine.dispose()

    app = FastAPI(title="Alfa hackathon backend", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.settings = settings
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "PUT"],
            allow_headers=["Authorization", "Content-Type"],
        )
    dummy_hash = password_hash("unregistered-account")
    buckets = OrderedDict()
    bucket_lock = threading.Lock()

    @app.middleware("http")
    async def request_limits(request, call_next):
        request_id = str(uuid.uuid4())
        started = time.monotonic()
        # Do not trust X-Forwarded-For unless a controlled proxy is configured externally.
        address = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with bucket_lock:
            bucket = buckets.setdefault(address, deque())
            buckets.move_to_end(address)
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            limited = len(bucket) >= settings.requests_per_minute
            if not limited:
                bucket.append(now)
            while len(buckets) > 10000:
                buckets.popitem(last=False)
        if limited:
            response = JSONResponse(
                {"detail": "Too many requests"}, status_code=429, headers={"Retry-After": "60"}
            )
        else:
            # Buffer with a hard cap, including chunked requests without Content-Length.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 32768:
                    break
            if len(body) > 32768:
                response = JSONResponse({"detail": "Request body too large"}, status_code=413)
            else:
                request._body = bytes(body)
                response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # No query strings, credentials, event bodies or upstream exception text in logs.
        route = request.scope.get("route")
        logger.info(
            "request=%s route=%s status=%d duration_ms=%.1f",
            request_id,
            getattr(route, "path", "unmatched"),
            response.status_code,
            (time.monotonic() - started) * 1000,
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_, error):
        return JSONResponse(
            {
                "detail": [
                    {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
                    for item in error.errors()
                ]
            },
            status_code=422,
        )

    @app.exception_handler(UpstreamError)
    async def upstream_error(_, error):
        return JSONResponse({"detail": error.message}, status_code=error.status)

    @app.exception_handler(CatalogUnavailable)
    async def no_catalog(_, error):
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_, error):
        logger.error("Database operation failed: %s", type(error).__name__)
        return JSONResponse({"detail": "Database unavailable"}, status_code=503)

    def db_session():
        with sessions() as db:
            yield db

    def current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
        db=Depends(db_session),
    ):
        token = db.get(SessionToken, token_digest(credentials.credentials)) if credentials else None
        if token is None or token.expires_at <= time.time():
            raise HTTPException(
                401, "Authentication required", headers={"WWW-Authenticate": "Bearer"}
            )
        user = db.get(User, token.user_id)
        if user is None:
            raise HTTPException(401, "Authentication required")
        return user

    def context(db, user):
        current = generation(db)
        allowed = visible_materials(db, user.id, current)
        service = upstream or DemoRecommender(list(allowed.values()), current)
        return current, allowed, service

    def check_generation(actual, expected):
        if actual != expected:
            raise HTTPException(409, "Catalog generation changed; refresh catalog and retry")

    def validate_payload(payload, current, field):
        if not isinstance(payload, dict) or not isinstance(payload.get(field), list):
            raise UpstreamError(502, "Invalid recommendation response")
        check_generation(payload.get("generation"), current)
        if any(not isinstance(item, dict) for item in payload[field]):
            raise UpstreamError(502, "Invalid recommendation items")

    @app.get("/health")
    def health(db=Depends(db_session)):
        return {
            "status": "ok",
            "mode": settings.reco_mode,
            "demo": settings.reco_mode == "demo",
            "generation": generation(db),
        }

    @app.get("/ready")
    def ready(db=Depends(db_session)):
        current = generation(db)
        if upstream:
            state = upstream.health()
            if state.get("status") != "ok":
                raise UpstreamError(503, "Algorithm is not ready")
            check_generation(state.get("generation"), current)
            if state.get("relevance_available") is False:
                raise UpstreamError(503, "Relevance artifacts unavailable")
        return {
            "status": "ready",
            "mode": settings.reco_mode,
            "generation": current,
            "note": "Readiness does not replace a real search smoke test",
        }

    @app.post("/api/v1/auth/register", status_code=201)
    def register(data: Credentials, db=Depends(db_session)):
        user = User(
            id=str(uuid.uuid4()),
            username=data.username,
            password_hash=password_hash(data.password),
            profile={},
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Username already registered") from None
        return issue_token(db, user.id, settings.token_ttl)

    @app.post("/api/v1/auth/login")
    def login(data: Credentials, db=Depends(db_session)):
        user = db.scalar(select(User).where(User.username == data.username))
        # Spend the same KDF work on unknown users to reduce username timing leaks.
        encoded = user.password_hash if user else dummy_hash
        valid = password_matches(data.password, encoded)
        if user is None or not valid:
            raise HTTPException(401, "Invalid username or password")
        return issue_token(db, user.id, settings.token_ttl)

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(credentials=Depends(bearer), user=Depends(current_user), db=Depends(db_session)):
        db.execute(
            delete(SessionToken).where(SessionToken.digest == token_digest(credentials.credentials))
        )
        db.commit()

    @app.get("/api/v1/me")
    def me(user=Depends(current_user)):
        return {"id": user.id, "username": user.username, "profile": user.profile}

    @app.put("/api/v1/me/profile")
    def update_profile(data: Profile, user=Depends(current_user), db=Depends(db_session)):
        user.profile = data.model_dump()
        db.commit()
        return user.profile

    @app.post("/api/v1/me/events", status_code=201)
    def event(data: ActivityInput, user=Depends(current_user), db=Depends(db_session)):
        current, allowed, _ = context(db, user)
        check_generation(data.generation, current)
        if data.entity_key not in allowed:
            raise HTTPException(404, "Material unavailable")
        if data.action in {"started", "completed"} and allowed[data.entity_key].kind != "course":
            raise HTTPException(422, "Only courses can be started or completed")
        existing = db.scalar(
            select(Activity).where(Activity.user_id == user.id, Activity.event_id == data.event_id)
        )
        if existing:
            if any(getattr(existing, key) != value for key, value in data.model_dump().items()):
                raise HTTPException(409, "event_id already used for a different event")
            return {"id": existing.id, "duplicate": True, "source": existing.source}
        activity = Activity(user_id=user.id, **data.model_dump(), source="self_reported")
        db.add(activity)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # Caller can safely retry the idempotent event after a concurrent insertion.
            raise HTTPException(409, "Concurrent event submission; retry") from None
        return {"id": activity.id, "duplicate": False, "source": activity.source}

    @app.get("/api/v1/me/events")
    def events(
        limit: int = Query(50, ge=1, le=100), user=Depends(current_user), db=Depends(db_session)
    ):
        current, allowed, _ = context(db, user)
        rows = db.scalars(
            select(Activity)
            .where(
                Activity.user_id == user.id,
                Activity.generation == current,
                Activity.entity_key.in_(list(allowed)),
            )
            .order_by(Activity.id.desc())
            .limit(limit)
        )
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

    @app.get("/api/v1/catalog")
    def catalog(
        q: str = Query("", max_length=300),
        kind: Kind | None = None,
        limit: int = Query(20, ge=1, le=50),
        offset: int = Query(0, ge=0, le=100000),
        user=Depends(current_user),
        db=Depends(db_session),
    ):
        current, allowed, _ = context(db, user)
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

    @app.get("/api/v1/suggest")
    def suggest(
        q: str = Query("", max_length=300),
        limit: int = Query(6, ge=1, le=10),
        user=Depends(current_user),
        db=Depends(db_session),
    ):
        current, allowed, _ = context(db, user)
        # Suggestions come from the authorized live catalog, not unfiltered ML facets.
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

    @app.get("/api/v1/search")
    def search(
        q: str = Query(min_length=1, max_length=300),
        kind: Kind | None = None,
        top: int = Query(5, ge=1, le=50),
        clarification_text: str | None = Query(None, min_length=1, max_length=100),
        user=Depends(current_user),
        db=Depends(db_session),
    ):
        if not q.strip() or any(ord(c) < 32 for c in q):
            raise HTTPException(422, "Query must contain text and no control characters")
        current, allowed, service = context(db, user)
        payload = service.search(q, 50, kind, clarification_text)
        validate_payload(payload, current, "results")
        alternatives = payload.get("alternatives", [])
        if not isinstance(alternatives, list) or any(not isinstance(x, dict) for x in alternatives):
            raise UpstreamError(502, "Invalid recommendation alternatives")
        results = enrich(payload["results"], allowed, top)
        primary_keys = {item["entity_key"] for item in results}
        alternative_cards = enrich(
            alternatives, {k: v for k, v in allowed.items() if k not in primary_keys}, top
        )
        # Never pass arbitrary upstream explanations: they can reference forbidden materials.
        return {
            "generation": current,
            "query": q,
            "mode": settings.reco_mode,
            "results": results,
            "alternatives": alternative_cards,
            "clarification": {"question": "Уточните вашу задачу", "allow_text": True}
            if payload.get("clarification")
            else None,
            "notice": "Результаты проверены по доступу; список может быть коротким или пустым",
        }

    def personalized(data, user, db, plan):
        current, allowed, service = context(db, user)
        check_generation(data.generation, current)
        viewed, completed = history(db, user.id, current, allowed)
        payload = service.recommend(
            current, user.profile.get("categories", []), viewed, completed if plan else None
        )
        validate_payload(payload, current, "steps" if plan else "results")
        if not plan:
            return {
                "generation": current,
                "mode": settings.reco_mode,
                "results": enrich(payload["results"], allowed, 5),
            }
        steps = payload["steps"]
        # Removal can invalidate sequence. Fail closed instead of claiming it is the same plan.
        if any(
            not isinstance(s.get("material"), dict)
            or s["material"].get("entity_key") not in allowed
            for s in steps
        ):
            return {
                "generation": current,
                "status": "insufficient_evidence",
                "steps": [],
                "notice": "Часть маршрута недоступна; требуется пересчёт",
            }
        safe_steps = []
        seen = set()
        for step in steps[:3]:
            key = step["material"]["entity_key"]
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
        if status not in {"needs_activity", "insufficient_evidence", "partial", "ready"}:
            status = "insufficient_evidence"
        if not safe_steps and status in {"ready", "partial"}:
            status = "insufficient_evidence"
        return {
            "generation": current,
            "mode": settings.reco_mode,
            "status": status,
            "steps": safe_steps,
            "notice": "Тематическая эвристика; история обучения указана пользователем",
        }

    @app.post("/api/v1/recommend")
    def recommend(data: GenerationRequest, user=Depends(current_user), db=Depends(db_session)):
        return personalized(data, user, db, False)

    @app.post("/api/v1/development-plan")
    def plan(data: GenerationRequest, user=Depends(current_user), db=Depends(db_session)):
        return personalized(data, user, db, True)

    return app
