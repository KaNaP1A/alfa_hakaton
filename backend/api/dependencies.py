"""Request-scoped services wired to application-owned ports."""

from collections.abc import Iterator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from domain.entities import User
from domain.ports import UnitOfWorkPort
from services.activity import ActivityService
from services.auth import AuthService
from services.catalog import CatalogService
from services.dependencies import ServiceDependencies
from services.health import HealthService
from services.profile import ProfileService
from services.recommendation_context import RecommendationContext
from services.recommendations import RecommendationService
from services.search import SearchService

bearer = HTTPBearer(auto_error=False)


def get_dependencies(request: Request) -> ServiceDependencies:
    dependencies: ServiceDependencies = request.app.state.services
    return dependencies


def get_uow(
    dependencies: ServiceDependencies = Depends(get_dependencies),
) -> Iterator[UnitOfWorkPort]:
    with dependencies.uow_factory() as uow:
        yield uow


def get_auth(
    dependencies: ServiceDependencies = Depends(get_dependencies),
    uow: UnitOfWorkPort = Depends(get_uow),
) -> AuthService:
    return AuthService(
        uow.users,
        uow,
        dependencies.passwords,
        dependencies.token_ttl,
        dependencies.dummy_hash,
    )


def get_profile(uow: UnitOfWorkPort = Depends(get_uow)) -> ProfileService:
    return ProfileService(uow.users, uow)


def get_catalog(uow: UnitOfWorkPort = Depends(get_uow)) -> CatalogService:
    return CatalogService(uow.catalog)


def get_activity(
    uow: UnitOfWorkPort = Depends(get_uow),
    catalog: CatalogService = Depends(get_catalog),
) -> ActivityService:
    return ActivityService(uow.activity, catalog, uow)


def get_model(
    dependencies: ServiceDependencies = Depends(get_dependencies),
    catalog: CatalogService = Depends(get_catalog),
) -> RecommendationContext:
    return RecommendationContext(
        catalog,
        dependencies.recommender,
        dependencies.demo_factory,
        dependencies.mode,
    )


def get_search(model: RecommendationContext = Depends(get_model)) -> SearchService:
    return SearchService(model)


def get_recommendations(
    model: RecommendationContext = Depends(get_model),
    uow: UnitOfWorkPort = Depends(get_uow),
) -> RecommendationService:
    return RecommendationService(model, uow.activity)


def get_health(
    dependencies: ServiceDependencies = Depends(get_dependencies),
    uow: UnitOfWorkPort = Depends(get_uow),
) -> HealthService:
    return HealthService(uow.catalog, dependencies.recommender, dependencies.mode)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    service: AuthService = Depends(get_auth),
) -> User:
    return service.authenticate(credentials.credentials if credentials else None)
