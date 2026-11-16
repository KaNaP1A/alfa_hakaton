import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from pydantic import ValidationError

from domain.commands import ActivityInput, GenerationRequest, Profile
from domain.entities import Material
from domain.entities import User as DomainUser
from domain.errors import AppError
from infrastructure.database import Activity, User, connect, initialize
from infrastructure.recommender import DemoRecommender
from repositories.backend import SqlAlchemyRepository
from repositories.unified_catalog import UnifiedCatalog, UnifiedCatalogRepository
from services.activity import ActivityService
from services.cards import card
from services.catalog import CatalogService
from services.commercial_order import prioritize
from services.recommendations import RecommendationService


def material(key, **changes):
    values = dict(
        entity_key=key,
        generation="generation-one",
        kind="course",
        title="Курс",
        description="",
        topics=["Финансы"],
        published=True,
        access="public",
        canonical_url=None,
        price_amount=None,
        price_currency=None,
    )
    return Material(**(values | changes))


class FakeCatalog:
    def __init__(self, items):
        self.items = items

    def generation(self):
        return "generation-one"

    def visible_materials(self, user_id, current):
        return dict(self.items)

    def import_catalog(self, data):
        raise AssertionError("Not used")


class UnifiedCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.generation = self.root / "generation-one"
        self.generation.mkdir()
        (self.root / "CURRENT.json").write_text(json.dumps({"generation": "generation-one"}))
        self.items = [
            {
                "entity_key": "course:old",
                "kind": "course",
                "supplement_display": {
                    "origin": "public_snapshot",
                    "title": "Публичное название",
                    "description": "Описание",
                    "topics": ["Финансы"],
                    "source_url": "https://kurs.alfabank.ru/courses/example/",
                },
                "conditional_offer": {
                    "kind": "fictional_simulation",
                    "price_rub": 3000,
                    "cost_rub": 1200,
                },
            },
            {
                "entity_key": "course:new",
                "kind": "course",
                "supplement_display": {
                    "origin": "synthetic",
                    "title": "Новый курс",
                    "description": "Описание",
                    "topics": ["Финансы"],
                    "source_url": "https://evil.example/course",
                },
                "conditional_offer": {
                    "kind": "fictional_simulation",
                    "price_rub": 2000,
                    "cost_rub": 500,
                },
            },
        ]
        self.write_catalog()

    def write_catalog(self):
        raw = json.dumps(self.items, ensure_ascii=False).encode()
        (self.generation / "catalog.json").write_bytes(raw)
        (self.generation / "manifest.json").write_text(
            json.dumps(
                {
                    "catalog_sha256": hashlib.sha256(raw).hexdigest(),
                    "profile_compatible_generations": ["old-generation"],
                }
            )
        )

    def test_real_access_and_price_preserved_and_supplement_unverified(self):
        source = material(
            "course:old", title="Название из БД", price_amount="499", price_currency="RUB"
        )
        repo = UnifiedCatalogRepository(
            FakeCatalog({"course:old": source}), UnifiedCatalog(self.root)
        )
        rows = repo.visible_materials("user", repo.generation())
        self.assertEqual(rows["course:old"].title, "Название из БД")
        self.assertTrue(rows["course:old"].access_verified)
        self.assertEqual(card(rows["course:old"])["price"]["status"], "known")
        self.assertFalse(rows["course:new"].access_verified)
        self.assertIsNone(rows["course:new"].canonical_url)
        self.assertIsNone(rows["course:new"].source_url)
        self.assertEqual(
            card(rows["course:new"])["price"],
            {"status": "conditional", "amount": "2000", "currency": "RUB"},
        )
        self.assertIsNone(source.conditional_price_rub)

    def test_unknown_currency_does_not_turn_snapshot_amount_into_confirmed_price(self):
        source = material("course:old", price_amount="10", price_currency=None)
        repo = UnifiedCatalogRepository(
            FakeCatalog({"course:old": source}), UnifiedCatalog(self.root)
        )
        self.assertEqual(
            card(repo.visible_materials("user", repo.generation())["course:old"])["price"][
                "status"
            ],
            "conditional",
        )

    def test_backup_only_listing_does_not_bypass_catalog_access(self):
        self.items[1]["supplement_display"]["origin"] = "historical_backup"
        self.write_catalog()
        catalog = UnifiedCatalog(self.root)
        hidden = UnifiedCatalogRepository(FakeCatalog({}), catalog)
        self.assertNotIn("course:new", hidden.visible_materials("user", hidden.generation()))
        visible = UnifiedCatalogRepository(
            FakeCatalog({"course:new": material("course:new")}), catalog
        )
        self.assertTrue(
            visible.visible_materials("user", visible.generation())["course:new"].access_verified
        )

    def test_public_listing_requires_a_trusted_source(self):
        self.items[0]["supplement_display"]["source_url"] = "https://untrusted.example/course"
        self.write_catalog()
        repo = UnifiedCatalogRepository(FakeCatalog({}), UnifiedCatalog(self.root))
        rows = repo.visible_materials("user", repo.generation())
        self.assertNotIn("course:old", rows)
        self.assertIn("course:new", rows)

    def test_title_candidate_does_not_inherit_identity_access_or_offers(self):
        self.items[0]["supplement_display"]["identity"] = "title_candidate_unverified"
        self.write_catalog()
        catalog = UnifiedCatalog(self.root)
        hidden = UnifiedCatalogRepository(FakeCatalog({}), catalog)
        self.assertNotIn("course:old", hidden.visible_materials("user", hidden.generation()))
        original = material("course:old", title="Оригинал из бэкапа")
        visible = UnifiedCatalogRepository(FakeCatalog({"course:old": original}), catalog)
        result = visible.visible_materials("user", visible.generation())["course:old"]
        self.assertEqual(result.title, original.title)
        self.assertIsNone(result.source_url)
        self.assertIsNone(result.conditional_price_rub)

    def test_unverified_course_cannot_be_marked_started_or_completed(self):
        row = material("course:new", access_verified=False)
        catalog = CatalogService(FakeCatalog({row.entity_key: row}))
        repository, transaction = Mock(), Mock()
        service = ActivityService(repository, catalog, transaction)
        user = DomainUser(id="u", username="user", password_hash="hash", profile={})
        for action in ("started", "completed"):
            with self.subTest(action=action), self.assertRaises(AppError) as error:
                service.event(
                    ActivityInput(
                        generation="generation-one",
                        event_id="one",
                        entity_key=row.entity_key,
                        action=action,
                    ),
                    user,
                )
            self.assertEqual(error.exception.status, 403)
        repository.add_event.assert_not_called()
        transaction.commit.assert_not_called()

    def test_profile_recommendations_receive_authorized_candidate_keys(self):
        class ProfileModel:
            def recommend_profile(self, generation, profile, viewed, completed, **kwargs):
                self.allowed = kwargs["allowed_keys"]
                return {"generation": generation, "results": [{"entity_key": "course:visible"}]}

        adapter = ProfileModel()
        context = Mock()
        context.mode = "python"
        context.context.return_value = (
            "generation-one",
            {"course:visible": material("course:visible")},
            adapter,
        )
        context.validate_payload.side_effect = lambda payload, generation, field: payload[field]
        activity = Mock()
        activity.history.return_value = ([], [])
        user = DomainUser(id="u", username="user", password_hash="hash", profile={})
        result = RecommendationService(context, activity).recommend(
            GenerationRequest(generation="generation-one"), user
        )
        self.assertEqual(adapter.allowed, {"course:visible"})
        self.assertEqual(result["results"][0]["entity_key"], "course:visible")

    def test_corrupt_catalog_and_unsafe_offer_are_rejected(self):
        (self.generation / "catalog.json").write_text("[]")
        with self.assertRaisesRegex(ValueError, "checksum"):
            UnifiedCatalog(self.root)
        self.items[0]["conditional_offer"]["cost_rub"] = 4000
        self.write_catalog()
        with self.assertRaisesRegex(ValueError, "conditional offer"):
            UnifiedCatalog(self.root)

    def test_commercial_priority_is_bounded_to_related_candidates(self):
        low = material("course:low", conditional_price_rub=1000, conditional_cost_rub=900)
        high = material("course:high", conditional_price_rub=3000, conditional_cost_rub=1000)
        other = material(
            "course:other",
            topics=["Технологии"],
            conditional_price_rub=5000,
            conditional_cost_rub=0,
        )
        allowed = {x.entity_key: x for x in (low, high, other)}
        original = [{"entity_key": x.entity_key} for x in (low, high, other)]
        result = prioritize(original, allowed)
        self.assertEqual(
            [x["entity_key"] for x in result], ["course:high", "course:low", "course:other"]
        )
        self.assertEqual(original[0]["entity_key"], "course:low")
        unrelated = [{"entity_key": "course:low"}, {"entity_key": "course:other"}]
        self.assertEqual(prioritize(unrelated, allowed), unrelated)

    def test_interest_directory_and_facet_selection_use_real_material_topics(self):
        a = material("course:a", topics=["Финансы"])
        b = material("course:b", topics=["Финансы и учет"])
        recommender = DemoRecommender([a, b], "generation-one")
        result = recommender.recommend_by_interests("generation-one", ["finance"], ["Финансы"], [])
        self.assertEqual(result["results"], [{"entity_key": "course:a"}])
        self.assertEqual(
            recommender.recommend_by_interests(
                "generation-one", ["finance"], ["Финансы"], ["course:a"]
            )["results"],
            [],
        )
        with self.assertRaises(ValidationError):
            Profile(categories=[], selected_facets=["Финансы"])
        with self.assertRaises(ValidationError):
            Profile(categories=["finance"], selected_facets=["Финансы", "финансы"])
        with self.assertRaises(ValidationError):
            Profile(categories=["finance", "finance"])
        with self.assertRaises(ValidationError):
            Profile(preferred_kinds=["course", "course"])

    def test_previous_generation_history_only_reuses_currently_allowed_ids(self):
        engine, sessions = connect("sqlite:///:memory:")
        initialize(engine)
        self.addCleanup(engine.dispose)
        with sessions() as db:
            db.add(User(id="u", username="user", password_hash="hash", profile={}))
            db.flush()
            for index, key in enumerate(["course:kept", "course:removed"], 1):
                db.add(
                    Activity(
                        user_id="u",
                        event_id=f"e{index}",
                        generation="old-generation",
                        entity_key=key,
                        action="viewed",
                        position=None,
                        source="self_reported",
                        created_at=float(index),
                    )
                )
            db.commit()
            repo = SqlAlchemyRepository(db, compatible_generations=("old-generation",))
            allowed = {"course:kept": material("course:kept")}
            viewed, completed = repo.history("u", "generation-one", allowed)
            self.assertEqual(viewed, ["course:kept"])
            self.assertEqual(completed, [])
            self.assertEqual(
                [
                    event.entity_key
                    for event in repo.events("u", "generation-one", list(allowed), 50)
                ],
                ["course:kept"],
            )


if __name__ == "__main__":
    unittest.main()
