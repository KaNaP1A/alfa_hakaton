"""Source-schema fixtures: no imported catalog and no API material table."""

import unittest
from unittest.mock import patch

from sqlalchemy import text

from api.dependencies import current_user
from app import create_app
from config.settings import Settings
from domain.commands import CatalogImport
from domain.entities import User
from domain.errors import AppError
from infrastructure.database import connect
from infrastructure.uow import SqlAlchemyUnitOfWork
from repositories.production_catalog import ProductionCatalogRepository


class ProductionCatalogTests(unittest.TestCase):
    def setUp(self):
        self.engine, self.sessions = connect("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as db:
            for name in ("Articles", "Courses", "Documents", "Webinars", "Podcasts", "Calculators"):
                db.exec_driver_sql(f'''CREATE TABLE "{name}" (
                    "Id" TEXT PRIMARY KEY, "Title" TEXT, "Description" TEXT, "Url" TEXT,
                    "StatusId" TEXT, "IsDeleted" BOOLEAN, "IsClosed" BOOLEAN,
                    "IsLesson" BOOLEAN, "TypeId" TEXT, "Cost" INTEGER)''')
            for sql in [
                'CREATE TABLE "Statuses" ("Id" TEXT, "Title" TEXT)',
                'CREATE TABLE "CourseTypes" ("Id" TEXT, "Title" TEXT, "IsDeleted" BOOLEAN)',
                'CREATE TABLE "ContentSettings" ("Id" TEXT, "EntityId" TEXT, "TypeId" TEXT, "IsDeleted" BOOLEAN)',
                'CREATE TABLE "Topics" ("Id" TEXT, "Title" TEXT, "IsPublic" BOOLEAN, "IsDeleted" BOOLEAN)',
                'CREATE TABLE "ContentSettingsTopics" ("ContentSettingsId" TEXT, "TopicId" TEXT)',
                'CREATE TABLE "CalculatorPages" ("Id" TEXT, "StatusId" TEXT, "IsDeleted" BOOLEAN, "Url" TEXT)',
                """INSERT INTO "Statuses" VALUES ('published', 'Опубликовано'), ('draft', 'Черновик')""",
                """INSERT INTO "CourseTypes" VALUES ('open', 'Открытый', 0), ('paid', 'Платный', 0)""",
                """INSERT INTO "ContentSettings" VALUES ('cs', 'document', 'open', 0)""",
                """INSERT INTO "Topics" VALUES ('topic', 'Финансы', 1, 0), ('secret', 'Hidden', 0, 0)""",
                """INSERT INTO "ContentSettingsTopics" VALUES ('cs', 'topic'), ('cs', 'secret')""",
                """INSERT INTO "CalculatorPages" VALUES ('calculator', 'draft', 0, 'https://example.org/calculator')""",
            ]:
                db.exec_driver_sql(sql)
            self.insert(db, "Courses", "course", cost=1250)
            self.insert(db, "Courses", "paid", access="paid")
            self.insert(db, "Articles", "draft", status="draft")
            self.insert(db, "Articles", "deleted", deleted=True)
            self.insert(db, "Articles", "closed", closed=True)
            self.insert(db, "Articles", "unknown", access="unknown")
            self.insert(db, "Articles", "lesson", lesson=True)
            # Documents.TypeId points to DocumentTypes. Use ContentSettings for access.
            self.insert(db, "Documents", "document", access="document-type", url="relative-slug")
            self.insert(db, "Calculators", "calculator")

    def insert(
        self,
        db,
        table,
        identifier,
        *,
        cost=None,
        access="open",
        status="published",
        deleted=False,
        closed=False,
        lesson=False,
        url="https://example.org/material",
    ):
        db.execute(
            text(f'''INSERT INTO "{table}" VALUES
            (:id, :title, :description, :url, :status, :deleted, :closed, :lesson, :type, :cost)'''),
            {
                "id": identifier,
                "title": "<b>Source title</b>",
                "description": "<p>Source description</p>",
                "url": url,
                "status": status,
                "deleted": deleted,
                "closed": closed,
                "lesson": lesson,
                "type": access,
                "cost": cost,
            },
        )

    def test_cards_read_source_tables_and_updates_without_import(self):
        with self.sessions() as db:
            repository = ProductionCatalogRepository(db, "index-v1")
            cards = repository.visible_materials("new-api-user", "index-v1")
            self.assertEqual(set(cards), {"course:course", "document:document"})
            self.assertEqual(cards["course:course"].title, "Source title")
            self.assertEqual(cards["course:course"].price_amount, "1250")
            self.assertIsNone(cards["course:course"].price_currency)
            self.assertEqual(cards["document:document"].topics, ["Финансы"])
            self.assertIsNone(cards["document:document"].canonical_url)
            db.execute(
                text('UPDATE "Courses" SET "Title" = :title WHERE "Id" = :id'),
                {"title": "Changed in PostgreSQL", "id": "course"},
            )
            self.assertEqual(
                repository.visible_materials("u", "index-v1")["course:course"].title,
                "Changed in PostgreSQL",
            )
            with self.assertRaises(AppError):
                repository.import_catalog(CatalogImport(generation="g", materials=[]))
            with self.assertRaises(AppError):
                repository.visible_materials("u", "stale")

    def test_uow_selects_source_repository_without_schema_creation(self):
        with SqlAlchemyUnitOfWork(
            self.sessions, catalog_source="postgres", generation="index-v1"
        ) as uow:
            self.assertEqual(uow.catalog.generation(), "index-v1")
            self.assertIn("course:course", uow.catalog.visible_materials("u", "index-v1"))
        with self.engine.connect() as db:
            tables = db.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).scalars()
            self.assertFalse(any(name.startswith("alfa_api_") for name in tables))

    def test_snapshot_settings_refuse_automatic_ddl(self):
        with self.assertRaises(ValueError):
            Settings(
                catalog_source="postgres", database_url="postgresql+psycopg://alfa@db/snapshot"
            )
        settings = Settings(
            catalog_source="postgres",
            auto_create_tables=False,
            database_url="postgresql+psycopg://alfa@db/snapshot",
        )
        from fastapi.testclient import TestClient

        with (
            patch("app.initialize") as initialize,
            patch("app.connect", return_value=(self.engine, self.sessions)),
        ):
            app = create_app(settings)
            app.dependency_overrides[current_user] = lambda: User("fixture", "fixture", "", {})
            with TestClient(app) as client:
                self.assertEqual(client.get("/health").status_code, 200)
                response = client.get("/api/v1/catalog")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(
                    {card["entity_key"] for card in response.json()["items"]},
                    {"course:course", "document:document"},
                )
                response = client.get("/api/v1/search", params={"q": "Source"})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(len(response.json()["results"]), 2)
            initialize.assert_not_called()
