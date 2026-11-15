import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app import create_app
from config.settings import Settings
from domain.entities import User as UserEntity
from infrastructure.database import User, connect, initialize
from infrastructure.uow import SqlAlchemyUnitOfWork


class UnitOfWorkTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.sessions = connect("sqlite:///:memory:")
        initialize(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_uncommitted_writes_are_rolled_back(self):
        with SqlAlchemyUnitOfWork(self.sessions) as uow:
            uow.repository.create_user(UserEntity("1", "alice", "hash", {}))
        with self.sessions() as db:
            self.assertIsNone(db.get(User, "1"))

    def test_commit_persists_entire_operation(self):
        with SqlAlchemyUnitOfWork(self.sessions) as uow:
            uow.repository.create_user(UserEntity("1", "alice", "hash", {}))
            uow.repository.save_token("digest", "1", 9999999999)
            uow.commit()
        with SqlAlchemyUnitOfWork(self.sessions) as uow:
            self.assertEqual(uow.repository.authenticated("digest", 0).username, "alice")

    def test_registration_rolls_back_user_when_token_write_fails(self):
        app = create_app(Settings(database_url="sqlite:///:memory:"))
        with TestClient(app) as client:
            with patch(
                "repositories.backend.SqlAlchemyRepository.save_token",
                side_effect=SQLAlchemyError("private DB error"),
            ):
                response = client.post(
                    "/api/v1/auth/register",
                    json={"username": "alice", "password": "a-long-password-123"},
                )
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("private DB error", response.text)
            with app.state.sessions() as db:
                self.assertIsNone(db.scalar(select(User)))
            retry = client.post(
                "/api/v1/auth/register",
                json={"username": "alice", "password": "a-long-password-123"},
            )
            self.assertEqual(retry.status_code, 201)
