from fastapi import APIRouter, Depends, Query, Response
from fastapi.security import HTTPAuthorizationCredentials

from api.dependencies import (
    bearer,
    current_user,
    get_activity,
    get_auth,
    get_catalog,
    get_health,
    get_profile,
    get_recommendations,
    get_search,
)
from api.errors import ErrorEnvelope
from domain.entities import User
from domain.responses import (
    CatalogResponse,
    EventResponse,
    HealthResponse,
    HistoryResponse,
    PlanResponse,
    RecommendationResponse,
    SearchResponse,
    SuggestResponse,
    TokenResponse,
    UserResponse,
)
from schemas.requests import ActivityInput, Credentials, GenerationRequest, Kind, Profile
from services.activity import ActivityService
from services.auth import AuthService
from services.catalog import CatalogService
from services.health import HealthService
from services.profile import ProfileService
from services.recommendations import RecommendationService
from services.search import SearchService

router = APIRouter(
    responses={
        status: {"model": ErrorEnvelope}
        for status in (400, 401, 404, 405, 409, 413, 422, 429, 500, 502, 503, 504)
    }
)


@router.get("/health")
def health(service: HealthService = Depends(get_health)) -> HealthResponse:
    return service.health()


@router.get("/ready")
def ready(service: HealthService = Depends(get_health)) -> HealthResponse:
    return service.ready()


@router.post("/api/v1/auth/register", status_code=201)
def register(data: Credentials, service: AuthService = Depends(get_auth)) -> TokenResponse:
    return service.register(data)


@router.post("/api/v1/auth/login")
def login(data: Credentials, service: AuthService = Depends(get_auth)) -> TokenResponse:
    return service.login(data)


@router.post("/api/v1/auth/logout", status_code=204)
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    user: User = Depends(current_user),
    service: AuthService = Depends(get_auth),
) -> Response:
    service.logout(credentials.credentials if credentials else "")
    return Response(status_code=204)


@router.get("/api/v1/me")
def me(
    user: User = Depends(current_user), service: ProfileService = Depends(get_profile)
) -> UserResponse:
    return service.me(user)


@router.put("/api/v1/me/profile")
def update_profile(
    data: Profile,
    user: User = Depends(current_user),
    service: ProfileService = Depends(get_profile),
) -> Profile:
    return service.update_profile(data, user)


@router.post("/api/v1/me/events", status_code=201)
def event(
    data: ActivityInput,
    user: User = Depends(current_user),
    service: ActivityService = Depends(get_activity),
) -> EventResponse:
    return service.event(data, user)


@router.get("/api/v1/me/events")
def events(
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(current_user),
    service: ActivityService = Depends(get_activity),
) -> HistoryResponse:
    return service.events(limit, user)


@router.get("/api/v1/catalog")
def catalog(
    q: str = Query("", max_length=300),
    kind: Kind | None = None,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0, le=100000),
    user: User = Depends(current_user),
    service: CatalogService = Depends(get_catalog),
) -> CatalogResponse:
    return service.catalog(q, kind, limit, offset, user)


@router.get("/api/v1/suggest")
def suggest(
    q: str = Query("", max_length=300),
    limit: int = Query(6, ge=1, le=10),
    user: User = Depends(current_user),
    service: SearchService = Depends(get_search),
) -> SuggestResponse:
    return service.suggest(q, limit, user)


@router.get("/api/v1/search")
def search(
    q: str = Query(min_length=1, max_length=300),
    kind: Kind | None = None,
    top: int = Query(5, ge=1, le=50),
    clarification_text: str | None = Query(None, min_length=1, max_length=100),
    selection_id: str | None = Query(None, min_length=1, max_length=150),
    selection_generation: str | None = Query(None, min_length=1, max_length=150),
    clarification_token: str | None = Query(None, min_length=1, max_length=2048),
    user: User = Depends(current_user),
    service: SearchService = Depends(get_search),
) -> SearchResponse:
    return service.search(
        q,
        kind,
        top,
        clarification_text,
        user,
        selection_id,
        selection_generation,
        clarification_token,
    )


@router.post("/api/v1/recommend")
def recommend(
    data: GenerationRequest,
    user: User = Depends(current_user),
    service: RecommendationService = Depends(get_recommendations),
) -> RecommendationResponse:
    return service.recommend(data, user)


@router.post("/api/v1/development-plan")
def plan(
    data: GenerationRequest,
    user: User = Depends(current_user),
    service: RecommendationService = Depends(get_recommendations),
) -> PlanResponse:
    return service.plan(data, user)
