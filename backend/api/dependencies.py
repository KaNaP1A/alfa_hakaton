from collections.abc import Iterator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from domain.entities import User
from infrastructure.uow import SqlAlchemyUnitOfWork
from services.backend import BackendService

bearer = HTTPBearer(auto_error=False)


def get_service(request: Request) -> Iterator[BackendService]:
    with SqlAlchemyUnitOfWork(request.app.state.sessions) as uow:
        yield BackendService(
            uow,
            request.app.state.upstream,
            request.app.state.passwords,
            request.app.state.demo_factory,
            request.app.state.settings,
            request.app.state.dummy_hash,
        )


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    service: BackendService = Depends(get_service),
) -> User:
    return service.authenticate(credentials.credentials if credentials else None)
