"""One SQLAlchemy session and transaction for an application operation."""

import logging
from types import TracebackType
from typing import Self

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from domain.errors import RepositoryConflict, StorageUnavailable
from domain.ports import ActivityRepository, CatalogRepository, UserRepository
from repositories.backend import SqlAlchemyRepository
from repositories.production_catalog import ProductionCatalogRepository


class SqlAlchemyUnitOfWork:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        catalog_source: str = "imported",
        generation: str = "production-snapshot",
    ) -> None:
        self._sessions = sessions
        self._catalog_source = catalog_source
        self._generation = generation
        self._catalog: CatalogRepository
        self.session: Session
        self.repository: SqlAlchemyRepository

    def __enter__(self) -> Self:
        try:
            self.session = self._sessions()
        except SQLAlchemyError as error:
            raise StorageUnavailable() from error
        self.repository = SqlAlchemyRepository(self.session)
        self._catalog = (
            ProductionCatalogRepository(self.session, self._generation)
            if self._catalog_source == "postgres"
            else self.repository
        )
        return self

    @property
    def users(self) -> UserRepository:
        return self.repository

    @property
    def catalog(self) -> CatalogRepository:
        return self._catalog

    @property
    def activity(self) -> ActivityRepository:
        return self.repository

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            try:
                self.rollback()
            finally:
                self.session.close()
        except SQLAlchemyError as error:
            raise StorageUnavailable() from error
        if isinstance(exc, SQLAlchemyError):
            logging.getLogger(__name__).error("Database operation failed: %s", type(exc).__name__)
            raise StorageUnavailable() from exc

    def commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as error:
            self.rollback()
            raise RepositoryConflict("Conflicting write; refresh and retry") from error

    def rollback(self) -> None:
        self.session.rollback()
