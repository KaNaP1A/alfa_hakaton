from __future__ import annotations

from domain.commands import Profile
from domain.entities import User
from domain.ports import (
    TransactionPort,
    UserRepository,
)
from domain.responses import (
    UserResponse,
)


class ProfileService:
    def __init__(self, users: UserRepository, transaction: TransactionPort) -> None:
        self.repository = users
        self.transaction = transaction

    def me(self, user: User) -> UserResponse:
        return {"id": user.id, "username": user.username, "profile": user.profile}

    def update_profile(self, data: Profile, user: User) -> Profile:
        user.profile = data.model_dump()
        self.repository.update_profile(user.id, user.profile)
        self.transaction.commit()
        return data
