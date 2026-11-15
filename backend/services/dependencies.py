"""Typed dependencies supplied by the composition root, without adapter imports."""

from dataclasses import dataclass

from domain.ports import DemoFactory, PasswordPort, RecommendationPort, UnitOfWorkFactory


@dataclass(frozen=True)
class ServiceDependencies:
    uow_factory: UnitOfWorkFactory
    passwords: PasswordPort
    recommender: RecommendationPort | None
    demo_factory: DemoFactory
    mode: str
    token_ttl: int
    dummy_hash: str
