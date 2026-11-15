import time

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "alfa_api_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    profile: Mapped[dict] = mapped_column(JSON, default=dict)


class SessionToken(Base):
    __tablename__ = "alfa_api_sessions"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey(User.id), index=True)
    expires_at: Mapped[float] = mapped_column(Float)


class CatalogState(Base):
    __tablename__ = "alfa_api_catalog_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generation: Mapped[str] = mapped_column(String(150))


class Material(Base):
    __tablename__ = "alfa_api_materials"
    entity_key: Mapped[str] = mapped_column(String(150), primary_key=True)
    generation: Mapped[str] = mapped_column(String(150), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(String, default="")
    topics: Mapped[list] = mapped_column(JSON, default=list)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    access: Mapped[str] = mapped_column(String(20), default="restricted")
    canonical_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    price_amount: Mapped[str | None] = mapped_column(String(40), nullable=True)
    price_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)


class Grant(Base):
    __tablename__ = "alfa_api_grants"
    __table_args__ = (UniqueConstraint("user_id", "entity_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey(User.id), index=True)
    # Deliberately survives catalog generations; source IDs must be stable.
    entity_key: Mapped[str] = mapped_column(String(150), index=True)
    expires_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class Activity(Base):
    __tablename__ = "alfa_api_activity"
    __table_args__ = (UniqueConstraint("user_id", "event_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey(User.id), index=True)
    event_id: Mapped[str] = mapped_column(String(80))
    generation: Mapped[str] = mapped_column(String(150))
    entity_key: Mapped[str] = mapped_column(String(150))
    action: Mapped[str] = mapped_column(String(20))
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="self_reported")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


def connect(url):
    options = {"pool_pre_ping": True}
    if url.startswith("sqlite:"):
        options["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            options["poolclass"] = StaticPool
    engine = create_engine(url, **options)
    if url.startswith("sqlite:"):

        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine, sessionmaker(engine, expire_on_commit=False)


def initialize(engine):
    # Initial hackathon schema, isolated from the source dump's tables.
    Base.metadata.create_all(engine)
