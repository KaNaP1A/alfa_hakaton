"""Exercise storage substitution through the public API, without SQL sessions."""

import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app import create_app
from config.settings import Settings
from services.ports import ActivityRepository, CatalogRepository


class MemoryUsers:
    def __init__(self):
        self.rows = {}
        self.tokens = {}

    def user(self, user_id):
        return self.rows.get(user_id)

    def by_username(self, username):
        return next((u for u in self.rows.values() if u.username == username), None)

    def authenticated(self, digest, now):
        token = self.tokens.get(digest)
        return self.user(token[0]) if token and token[1] > now else None

    def create_user(self, user):
        self.rows[user.id] = user

    def save_token(self, digest, user_id, expires_at):
        self.tokens[digest] = (user_id, expires_at)

    def revoke_token(self, digest):
        self.tokens.pop(digest, None)

    def update_profile(self, user_id, profile):
        self.rows[user_id].profile = profile


class ServiceContractTests(unittest.TestCase):
    def test_api_accepts_alternative_storage_and_shares_request_transaction(self):
        users = MemoryUsers()
        catalog = Mock(spec=CatalogRepository)
        catalog.generation.return_value = "memory-v1"
        catalog.visible_materials.return_value = {}
        activity = Mock(spec=ActivityRepository)
        activity.events.return_value = []
        activity.history.return_value = ([], [])
        transactions = []

        class MemoryUnitOfWork:
            def __init__(self):
                self.users = users
                self.catalog = catalog
                self.activity = activity
                self.commits = 0

            def __enter__(self):
                transactions.append(self)
                return self

            def __exit__(self, *args):
                self.rollback()

            def commit(self):
                self.commits += 1

            def rollback(self):
                pass  # This fixture checks wiring; SQL rollback is covered by test_uow.

        with patch("app.connect") as connect:
            app = create_app(Settings(), uow_factory=MemoryUnitOfWork)
            with TestClient(app) as api:
                credentials = {"username": "alice", "password": "a-long-password-123"}
                response = api.post("/api/v1/auth/register", json=credentials)
                self.assertEqual(response.status_code, 201, response.text)
                self.assertEqual(transactions[-1].commits, 1)
                headers = {"Authorization": "Bearer " + response.json()["access_token"]}
                before = len(transactions)
                me = api.get("/api/v1/me", headers=headers)
                self.assertEqual(me.json()["username"], "alice")
                self.assertEqual(len(transactions), before + 1)
                for endpoint in ("catalog", "search?q=coffee", "me/events"):
                    response = api.get("/api/v1/" + endpoint, headers=headers)
                    self.assertEqual(response.status_code, 200, response.text)
                response = api.put(
                    "/api/v1/me/profile", json={"categories": ["business"]}, headers=headers
                )
                self.assertEqual(response.status_code, 200, response.text)
                response = api.post("/api/v1/auth/logout", headers=headers)
                self.assertEqual(response.status_code, 204)
                self.assertEqual(api.get("/api/v1/me", headers=headers).status_code, 401)
            connect.assert_not_called()
