"""Export the visible catalogue into a new, empty local PostgreSQL demo database.

Only content fields required by ProductionCatalogRepository are copied. User
activity, ratings, account data and source schema are never copied. The source
and destination URLs are read from the environment and are not logged.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from repositories.production_catalog import ProductionCatalogRepository, TABLES

ROOT = Path(__file__).resolve().parents[1]
CONTACT = re.compile(
    r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
    r"|(?<!\d)(?:\+7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}[\s()\-]*\d{2}[\s()\-]*\d{2}(?!\d)"
)


def public_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "kurs.alfabank.ru"
        or parsed.username
    ):
        return None
    return urlunsplit(("https", "kurs.alfabank.ru", parsed.path, "", ""))


def main() -> None:
    source_url = os.environ["ALFA_SOURCE_DATABASE_URL"]
    target_url = os.environ["ALFA_PUBLIC_TARGET_URL"]
    target = urlsplit(target_url.replace("postgresql+psycopg:", "postgresql:", 1))
    if target.hostname not in {"127.0.0.1", "localhost"} or not target.path.endswith(
        "_demo"
    ):
        raise ValueError(
            "The target must be a local disposable database ending in _demo"
        )
    if source_url == target_url:
        raise ValueError("Source and target must be different databases")

    bundle = ROOT / "models" / "recommender" / "catalog"
    generation = json.loads((bundle / "CURRENT.json").read_text())["generation"]
    published_keys = {
        row["entity_key"]
        for row in json.loads((bundle / generation / "catalog.json").read_text())
    }
    source = create_engine(source_url)
    try:
        with Session(source) as session:
            visible = ProductionCatalogRepository(session, "demo").visible_materials(
                "", "demo"
            )
    finally:
        source.dispose()
    materials = [item for key, item in sorted(visible.items()) if key in published_keys]
    if not materials:
        raise ValueError("No visible cards matched the published model catalogue")
    for item in materials:
        if CONTACT.search(" ".join([item.title, item.description, *item.topics])):
            raise ValueError(
                "A public catalogue field contains contact information; review it first"
            )

    destination = create_engine(target_url)
    try:
        with destination.begin() as connection:
            count = connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
                )
            ).scalar_one()
            if count:
                raise ValueError("The target database is not empty")
            for statement in (
                'CREATE TABLE "Statuses" ("Id" text, "Title" text)',
                'CREATE TABLE "CourseTypes" ("Id" text, "Title" text, "IsDeleted" boolean)',
                'CREATE TABLE "ContentSettings" ("Id" text, "EntityId" text, '
                '"TypeId" text, "IsDeleted" boolean)',
                'CREATE TABLE "Topics" ("Id" text, "Title" text, '
                '"IsPublic" boolean, "IsDeleted" boolean)',
                'CREATE TABLE "ContentSettingsTopics" ("ContentSettingsId" text, "TopicId" text)',
                'CREATE TABLE "CalculatorPages" ("Id" text, "StatusId" text, '
                '"IsDeleted" boolean, "Url" text)',
            ):
                connection.execute(text(statement))
            for table in TABLES:
                connection.execute(
                    text(
                        f'CREATE TABLE "{table}" ("Id" text, "Title" text, "Description" text, '
                        '"Url" text, "StatusId" text, "IsDeleted" boolean, "IsClosed" boolean, '
                        '"IsLesson" boolean, "TypeId" text, "Cost" text)'
                    )
                )
            connection.execute(
                text('INSERT INTO "Statuses" VALUES (:id, :title)'),
                {"id": "published", "title": "Опубликовано"},
            )
            connection.execute(
                text('INSERT INTO "CourseTypes" VALUES (:id, :title, false)'),
                {"id": "open", "title": "Открытый"},
            )
            topics: dict[str, str] = {}
            settings, links, by_table = [], [], {table: [] for table in TABLES}
            table_by_kind = {kind: table for table, kind in TABLES.items()}
            pages = []
            for item in materials:
                _, identifier = item.entity_key.split(":", 1)
                setting_id = item.entity_key
                settings.append({"id": setting_id, "entity": identifier})
                for title in item.topics:
                    topic_id = hashlib.sha256(title.encode("utf-8")).hexdigest()[:24]
                    topics[topic_id] = title
                    links.append({"setting": setting_id, "topic": topic_id})
                by_table[table_by_kind[item.kind]].append(
                    {
                        "id": identifier,
                        "title": item.title,
                        "description": item.description,
                        "url": public_url(item.canonical_url),
                        "cost": item.price_amount,
                    }
                )
                if item.kind == "calculator":
                    pages.append(
                        {"id": identifier, "url": public_url(item.canonical_url)}
                    )
            connection.execute(
                text(
                    "INSERT INTO \"ContentSettings\" VALUES (:id, :entity, 'open', false)"
                ),
                settings,
            )
            if topics:
                connection.execute(
                    text('INSERT INTO "Topics" VALUES (:id, :title, true, false)'),
                    [{"id": key, "title": value} for key, value in topics.items()],
                )
            if links:
                connection.execute(
                    text(
                        'INSERT INTO "ContentSettingsTopics" VALUES (:setting, :topic)'
                    ),
                    links,
                )
            if pages:
                connection.execute(
                    text(
                        "INSERT INTO \"CalculatorPages\" VALUES (:id, 'published', false, :url)"
                    ),
                    pages,
                )
            for table, rows in by_table.items():
                if rows:
                    connection.execute(
                        text(
                            f'INSERT INTO "{table}" VALUES (:id, :title, :description, :url, '
                            "'published', false, false, false, 'open', :cost)"
                        ),
                        rows,
                    )
    finally:
        destination.dispose()
    print(
        f"Exported {len(materials)} visible cards and {len(topics)} topics; no user tables copied."
    )


if __name__ == "__main__":
    main()
