from __future__ import annotations

import secrets
import time
import uuid

from domain.commands import Credentials
from domain.entities import User
from domain.errors import AppError
from domain.ports import (
    PasswordPort,
    TransactionPort,
    UserRepository,
)
from domain.responses import (
    TokenResponse,
)
from domain.security import token_digest


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        transaction: TransactionPort,
        passwords: PasswordPort,
        token_ttl: int,
        dummy_hash: str,
    ) -> None:
        self.repository = users
        self.transaction = transaction
        self.passwords = passwords
        self.token_ttl = token_ttl
        self.dummy_hash = dummy_hash

    def authenticate(self, token: str | None) -> User:
        user = self.repository.authenticated(token_digest(token), time.time()) if token else None
        if user is None:
            raise AppError(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
        return user

    def issue_token(self, user_id: str) -> TokenResponse:
        token = secrets.token_urlsafe(32)
        self.repository.save_token(token_digest(token), user_id, time.time() + self.token_ttl)
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": self.token_ttl,
        }

    def register(self, data: Credentials) -> TokenResponse:
        user = User(
            id=str(uuid.uuid4()),
            username=data.username,
            password_hash=self.passwords.hash(data.password),
            profile={},
        )
        self.repository.create_user(user)
        result = self.issue_token(user.id)
        self.transaction.commit()
        return result

    def login(self, data: Credentials) -> TokenResponse:
        user = self.repository.by_username(data.username)
        encoded = user.password_hash if user else self.dummy_hash
        valid = self.passwords.matches(data.password, encoded)
        if user is None or not valid:
            raise AppError(401, "Invalid username or password")
        result = self.issue_token(user.id)
        self.transaction.commit()
        return result

    def logout(self, token: str) -> None:
        self.repository.revoke_token(token_digest(token))
        self.transaction.commit()
