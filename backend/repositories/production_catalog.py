"""Read catalog cards directly from the restored production schema.

No JSON import, staging table, ML metadata or schema creation is used here.
Production IDs retain the same kind:UUID convention as alfa_reco.
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import MetaData, Table, select
from sqlalchemy.orm import Session

from domain.commands import CatalogImport
from domain.entities import Material
from domain.errors import AppError

# Table identifiers are a fixed allowlist, never derived from request input.
TABLES = {
    "Articles": "article",
    "Courses": "course",
    "Documents": "document",
    "Webinars": "webinar",
    "Podcasts": "podcast",
    "Calculators": "calculator",
}


def plain_text(value: object) -> str:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", str(value or ""), flags=re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", text))).strip()


def source_url(value: object) -> str | None:
    value = str(value or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    # Snapshot URLs also contain slugs. Do not invent routing rules or a host.
    if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
        return value
    return None


class ProductionCatalogRepository:
    def __init__(self, db: Session, generation: str) -> None:
        self.db = db
        self._generation = generation
        self._metadata = MetaData()

    def _table(self, name: str) -> Table:
        # Reflection reads schema metadata; it never creates or alters a table.
        schema = (
            "public"
            if self.db.bind is not None and self.db.bind.dialect.name == "postgresql"
            else None
        )
        return Table(
            name,
            self._metadata,
            schema=schema,
            autoload_with=self.db.connection(),
            resolve_fks=False,
        )

    def _rows(self, name: str, columns: tuple[str, ...]) -> list[dict[str, Any]]:
        table = self._table(name)
        selected = [table.c[column] for column in columns if column in table.c]
        return [dict(row) for row in self.db.execute(select(*selected)).mappings()]

    def generation(self) -> str:
        # Read the source even for health checks; do not report a disconnected DB as healthy.
        statuses = self._table("Statuses")
        if self.db.execute(select(statuses.c.Id).limit(1)).first() is None:
            raise AppError(503, "Restore the production snapshot before using the catalog")
        # Index compatibility identifier, configured alongside the model, not card data.
        return self._generation

    def import_catalog(self, data: CatalogImport) -> None:
        raise AppError(409, "Production catalog is read directly from PostgreSQL")

    def visible_materials(self, user_id: str, current: str) -> dict[str, Material]:
        if current != self._generation:
            raise AppError(409, "Catalog generation changed")
        statuses = {str(r["Id"]): r["Title"] for r in self._rows("Statuses", ("Id", "Title"))}
        types = {
            str(r["Id"]): r["Title"]
            for r in self._rows("CourseTypes", ("Id", "Title", "IsDeleted"))
            if not r["IsDeleted"]
        }
        settings = {
            str(r["EntityId"]): r
            for r in self._rows("ContentSettings", ("Id", "EntityId", "TypeId", "IsDeleted"))
            if not r["IsDeleted"]
        }
        topics = {
            str(r["Id"]): plain_text(r["Title"])
            for r in self._rows("Topics", ("Id", "Title", "IsPublic", "IsDeleted"))
            if r["IsPublic"] and not r["IsDeleted"]
        }
        topic_map: dict[str, list[str]] = defaultdict(list)
        for row in self._rows("ContentSettingsTopics", ("ContentSettingsId", "TopicId")):
            topic = topics.get(str(row["TopicId"]))
            if topic:
                topic_map[str(row["ContentSettingsId"])].append(topic)
        pages = {
            str(r["Id"]): r
            for r in self._rows("CalculatorPages", ("Id", "StatusId", "IsDeleted", "Url"))
            if not r["IsDeleted"]
        }
        result = {}
        for table, kind in TABLES.items():
            rows = self._rows(
                table,
                (
                    "Id",
                    "Title",
                    "Description",
                    "Url",
                    "StatusId",
                    "IsDeleted",
                    "IsClosed",
                    "IsLesson",
                    "TypeId",
                    "Cost",
                ),
            )
            for row in rows:
                identifier = str(row["Id"])
                page = pages.get(identifier, {}) if kind == "calculator" else row
                if row["IsDeleted"] or row.get("IsClosed") or row.get("IsLesson"):
                    continue
                if statuses.get(str(page.get("StatusId"))) != "Опубликовано":
                    continue
                setting = settings.get(identifier, {})
                # Documents.TypeId references DocumentTypes, never CourseTypes.
                type_id = (
                    row.get("TypeId")
                    if kind in {"article", "course", "podcast", "webinar"}
                    else None
                )
                type_id = type_id or setting.get("TypeId")
                access = types.get(str(type_id))
                # The dump has no Users table to authenticate site identities/entitlements.
                # New API identities cannot claim source CourseUserBindings or subscriptions.
                if access != "Открытый":
                    continue
                key = f"{kind}:{identifier}"
                title = plain_text(row["Title"])
                if not title:
                    continue
                cost = row.get("Cost")
                # Cost has no currency column in this snapshot. Preserve the amount,
                # leave currency unknown rather than assuming RUB or converting units.
                result[key] = Material(
                    entity_key=key,
                    generation=current,
                    kind=kind,
                    title=title,
                    description=plain_text(row.get("Description")),
                    topics=sorted(set(topic_map.get(str(setting.get("Id")), []))),
                    published=True,
                    access="public",
                    canonical_url=source_url(page.get("Url")),
                    price_amount=str(cost) if cost is not None else None,
                    price_currency=None,
                )
        return result
