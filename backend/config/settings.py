from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./backend.sqlite3"
    catalog_source: str = "imported"
    catalog_generation: str = "production-snapshot"
    auto_create_tables: bool = True
    reco_mode: str = "demo"
    reco_catalog: str = "../models/recommender/catalog"
    unified_catalog: str | None = None
    reco_url: str = "http://127.0.0.1:8000"
    reco_host_header: str | None = None
    request_timeout: float = 30
    token_ttl: int = 86400
    requests_per_minute: int = 120
    cors_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.catalog_source not in {"imported", "postgres"}:
            raise ValueError("ALFA_CATALOG_SOURCE must be imported or postgres")
        if self.catalog_source == "postgres":
            if not self.database_url.startswith("postgresql+psycopg:"):
                raise ValueError("Production catalog requires PostgreSQL")
            if self.auto_create_tables:
                raise ValueError("Production snapshot requires ALFA_AUTO_CREATE_TABLES=false")
        if not self.catalog_generation or len(self.catalog_generation) > 150:
            raise ValueError("Invalid ALFA_CATALOG_GENERATION")
        if self.reco_mode not in {"demo", "http", "python"}:
            raise ValueError("ALFA_RECO_MODE must be demo, http or python")
        if not self.database_url.startswith(("sqlite:", "postgresql+psycopg:")):
            raise ValueError("Use sqlite or postgresql+psycopg database URL")
        parsed = urlsplit(self.reco_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("Invalid ALFA_RECO_URL")
        if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("ALFA_RECO_URL must be an origin without path/query/fragment")
        if self.reco_host_header and any((c in self.reco_host_header for c in "\r\n")):
            raise ValueError("Invalid ALFA_RECO_HOST_HEADER")
        for origin in self.cors_origins:
            url = urlsplit(origin)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.path
                or url.query
                or url.fragment
            ):
                raise ValueError("CORS origins must be explicit HTTP(S) origins")
        if self.request_timeout <= 0 or self.token_ttl <= 0 or self.requests_per_minute <= 0:
            raise ValueError("Timeout, token TTL and rate limit must be positive")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.getenv("ALFA_DATABASE_URL", "sqlite:///./backend.sqlite3"),
            catalog_source=os.getenv("ALFA_CATALOG_SOURCE", "imported"),
            catalog_generation=os.getenv("ALFA_CATALOG_GENERATION", "production-snapshot"),
            auto_create_tables=os.getenv("ALFA_AUTO_CREATE_TABLES", "true").lower() == "true",
            reco_mode=os.getenv("ALFA_RECO_MODE", "demo"),
            reco_catalog=os.getenv("ALFA_RECO_CATALOG", "../models/recommender/catalog"),
            unified_catalog=os.getenv("ALFA_UNIFIED_CATALOG") or None,
            reco_url=os.getenv("ALFA_RECO_URL", "http://127.0.0.1:8000"),
            reco_host_header=os.getenv("ALFA_RECO_HOST_HEADER") or None,
            request_timeout=float(os.getenv("ALFA_RECO_TIMEOUT", "30")),
            token_ttl=int(os.getenv("ALFA_TOKEN_TTL", "86400")),
            requests_per_minute=int(os.getenv("ALFA_RATE_LIMIT", "120")),
            cors_origins=tuple(
                (x.strip() for x in os.getenv("ALFA_CORS_ORIGINS", "").split(",") if x.strip())
            ),
        )
