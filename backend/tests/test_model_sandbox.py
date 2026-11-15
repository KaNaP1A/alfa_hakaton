import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select

from infrastructure.database import Material, connect
from scripts.seed_model_sandbox import seed


class ModelSandboxTests(unittest.TestCase):
    def test_fixture_omits_glossary_prices_urls_and_never_overwrites_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "g1").mkdir()
            (root / "CURRENT.json").write_text('{"generation":"g1"}')
            (root / "g1" / "catalog.json").write_text(
                json.dumps(
                    [
                        {
                            "entity_key": "course:a",
                            "kind": "course",
                            "title": "Course",
                            "canonical_url": "https://example.com/stale",
                            "price_amount": "900",
                        },
                        {"entity_key": "glossary:b", "kind": "glossary", "title": "Term"},
                    ]
                )
            )
            database = root / "sandbox.sqlite3"
            data = seed(root, database)
            self.assertEqual(len(data.materials), 1)
            engine, sessions = connect("sqlite:///" + str(database))
            try:
                with sessions() as session:
                    material = session.scalar(select(Material))
                    self.assertEqual(material.entity_key, "course:a")
                    self.assertIsNone(material.canonical_url)
                    self.assertIsNone(material.price_amount)
                    self.assertTrue(material.published)
                    self.assertEqual(material.access, "public")
            finally:
                engine.dispose()
            original = database.read_bytes()
            with self.assertRaises(FileExistsError):
                seed(root, database)
            self.assertEqual(database.read_bytes(), original)

    def test_invalid_generation_does_not_create_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "CURRENT.json").write_text('{"generation":"../outside"}')
            database = root / "sandbox.sqlite3"
            with self.assertRaisesRegex(ValueError, "Invalid catalog generation"):
                seed(root, database)
            self.assertFalse(database.exists())
