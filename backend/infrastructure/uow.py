"""One SQLAlchemy session and transaction for an application operation."""

from types import TracebackType
from typing import Self

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from domain.errors import RepositoryConflict
from repositories.backend import SqlAlchemyRepository


class SqlAlchemyUnitOfWork:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions
        self.session: Session
        self.repository: SqlAlchemyRepository

    def __enter__(self) -> Self:
        self.session = self._sessions()
        self.repository = SqlAlchemyRepository(self.session)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self.rollback()
        finally:
            self.session.close()

    def commit(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as error:
            self.rollback()
            raise RepositoryConflict("Conflicting write; refresh and retry") from error

    def rollback(self) -> None:
        self.session.rollback()
