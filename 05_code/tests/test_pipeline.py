import io
import sqlite3
import unittest
from unittest.mock import patch

from alfa_reco.cli import bm25, clean, decode_copy, import_copy, normalize, safe_url


class PipelineTests(unittest.TestCase):
    def connection(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        return connection

    def test_copy_escapes_and_null_are_distinct(self):
        self.assertIsNone(decode_copy(r"\N"))
        self.assertEqual(decode_copy(r"\\N"), r"\N")
        self.assertEqual(decode_copy(r"текст\tстрока\n\\"), "текст\tстрока\n\\")
        self.assertEqual(decode_copy(r"\101"), "A")
        self.assertEqual(decode_copy(r"\303\251"), "é")

    def test_copy_does_not_execute_sql(self):
        source = 'DROP TABLE important;\nCOPY public."A" ("Id", "Text") FROM stdin;\n1\tDROP TABLE important;\n\\.\n'
        c = self.connection()
        c.execute("CREATE TABLE important (id TEXT)")
        self.assertEqual(import_copy(iter(io.StringIO(source)), c), {"A": 1})
        self.assertEqual(c.execute("SELECT Text FROM A").fetchone()[0], "DROP TABLE important;")
        c.execute("SELECT * FROM important")

    def test_sql_like_identifier_is_only_a_table_name(self):
        connection = self.connection()
        connection.execute("CREATE TABLE important (id TEXT)")
        source = 'COPY public."A; DROP TABLE important;--" ("Id") FROM stdin;\n1\n\\.\n'
        self.assertEqual(
            import_copy(iter(io.StringIO(source)), connection), {"A; DROP TABLE important;--": 1}
        )
        connection.execute("SELECT * FROM important")

    def test_truncated_copy_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unterminated"):
            import_copy(
                iter(io.StringIO('COPY public."A" ("Id") FROM stdin;\n1\n')),
                self.connection(),
            )

    def test_copy_width_rejected(self):
        with self.assertRaisesRegex(ValueError, "width"):
            import_copy(
                iter(io.StringIO('COPY public."A" ("Id") FROM stdin;\n1\t2\n\\.\n')),
                self.connection(),
            )

    def test_html_and_links(self):
        self.assertEqual(
            clean("<script>alert(1)</script><p>Пример&nbsp;текста</p>"), "Пример текста"
        )
        self.assertIsNone(safe_url("javascript:alert(1)"))
        self.assertIsNone(safe_url("course-slug"))
        self.assertIsNone(safe_url("https://kurs.alfabank.ru.evil.test/x"))
        self.assertEqual(
            safe_url("https://kurs.alfabank.ru/courses/"),
            "https://kurs.alfabank.ru/courses/",
        )

    def test_bm25_exact_term_and_no_match(self):
        docs = [
            {"search_text": "Безопасная разработка Frontend"},
            {"search_text": "Удержание сотрудников"},
        ]
        scores = bm25("Frontend", docs)
        self.assertGreater(scores[0], scores[1])
        self.assertEqual(bm25("несуществующееслово", docs), [0, 0])

    def test_published_document_without_date_is_kept_unknown_access(self):
        source = {
            "Statuses": [{"Id": "published", "Title": "Опубликовано"}],
            "CourseTypes": [],
            "ContentSettings": [],
            "Topics": [],
            "Tags": [],
            "Industries": [],
            "ContentSettingsTopics": [],
            "ContentSettingsTags": [],
            "ContentSettingsIndustries": [],
            "Documents": [
                {
                    "Id": "doc",
                    "StatusId": "published",
                    "Title": "Договор",
                    "Published": None,
                    "Cost": None,
                }
            ],
        }
        with (
            patch("alfa_reco.cli.KINDS", {"Documents": "document"}),
            patch("alfa_reco.cli.rows", side_effect=lambda c, t: source[t]),
        ):
            catalog, _ = normalize(None)
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["access_type"], "unknown")
        self.assertIsNone(catalog[0]["price_raw"])
        self.assertIn("url_unverified", catalog[0]["data_quality_flags"])

    def test_course_null_cost_and_article_type_have_distinct_provenance(self):
        source = {
            "Statuses": [{"Id": "pub", "Title": "Опубликовано"}],
            "CourseTypes": [{"Id": "open", "Title": "Открытый"}],
            "ContentSettings": [{"Id": "s", "EntityId": "a", "TypeId": "open"}],
            "Topics": [], "Tags": [], "Industries": [],
            "ContentSettingsTopics": [], "ContentSettingsTags": [], "ContentSettingsIndustries": [],
            "Courses": [{"Id": "c", "StatusId": "pub", "Title": "Курс", "Cost": None,
                         "Target": "Для предпринимателей"}],
            "Articles": [{"Id": "a", "StatusId": "pub", "Title": "Статья", "TypeId": None}],
        }
        with (patch("alfa_reco.cli.KINDS", {"Courses": "course", "Articles": "article"}),
              patch("alfa_reco.cli.rows", side_effect=lambda c, t: source[t])):
            catalog, _ = normalize(None)
        by_kind = {item["kind"]: item for item in catalog}
        self.assertTrue(by_kind["course"]["course_cost_available"])
        self.assertIsNone(by_kind["course"]["price_raw"])
        self.assertEqual(by_kind["course"]["target_audience"], "Для предпринимателей")
        self.assertEqual(by_kind["article"]["access_type"], "unknown")

    def test_closed_and_draft_materials_are_excluded(self):
        source = {
            "Statuses": [
                {"Id": "pub", "Title": "Опубликовано"},
                {"Id": "draft", "Title": "Черновик"},
            ],
            "CourseTypes": [],
            "ContentSettings": [],
            "Topics": [],
            "Tags": [],
            "Industries": [],
            "ContentSettingsTopics": [],
            "ContentSettingsTags": [],
            "ContentSettingsIndustries": [],
            "Courses": [
                {"Id": "a", "StatusId": "draft", "Title": "A"},
                {"Id": "b", "StatusId": "pub", "IsClosed": "t", "Title": "B"},
            ],
        }
        with (
            patch("alfa_reco.cli.KINDS", {"Courses": "course"}),
            patch("alfa_reco.cli.rows", side_effect=lambda c, t: source[t]),
        ):
            catalog, excluded = normalize(None)
        self.assertEqual(catalog, [])
        self.assertEqual(sum(excluded.values()), 2)


if __name__ == "__main__":
    unittest.main()


class ModelFingerprintTests(unittest.TestCase):
    def test_local_model_mutation_is_detectable(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from alfa_reco.cli import model_fingerprint

        names = [
            "model.safetensors",
            "config.json",
            "modules.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "1_Pooling/config.json",
        ]
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode())
            before = model_fingerprint(root)
            (root / "tokenizer.json").write_text("changed")
            self.assertNotEqual(before, model_fingerprint(root))
            (root / "model.safetensors").unlink()
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                model_fingerprint(root)
