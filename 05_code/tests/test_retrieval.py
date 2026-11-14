import unittest

from alfa_reco.content import enrich_content, html_text, make_units
from alfa_reco.retrieval import FieldRetriever, RankingConfig


class ContentTests(unittest.TestCase):
    def test_sanitize_script_and_hidden_content(self):
        self.assertEqual(
            html_text("<p>Полезно</p><script>secret</script><style>x</style><p>текст</p>"),
            "Полезно текст",
        )

    def test_index_only_open_public_article_and_eligible_lessons(self):
        catalog = [
            {
                "kind": "article",
                "source_id": "a",
                "access_type": "open",
                "content_public_flag": "t",
                "provenance": {},
            },
            {
                "kind": "article",
                "source_id": "b",
                "access_type": "unknown",
                "content_public_flag": "t",
                "provenance": {},
            },
            {
                "kind": "course",
                "source_id": "c",
                "access_type": "open",
                "content_public_flag": None,
                "provenance": {},
                "lessons": [{"lesson_id": "l", "is_trial": True}],
            },
        ]
        articles = [
            {"ArticleId": "a", "Id": "1", "Order": "0", "HtmlContent": "<p>public</p>"},
            {"ArticleId": "b", "Id": "2", "Order": "0", "HtmlContent": "private"},
        ]
        lessons = [
            {"LessonId": "l", "Id": "3", "Order": "0", "HtmlContent": "lesson"},
            {"LessonId": "hidden", "Id": "4", "Order": "0", "HtmlContent": "hidden"},
        ]
        report = enrich_content(catalog, articles, lessons)
        self.assertEqual(report["article_bodies"], 1)
        self.assertEqual(catalog[0]["body"], "public")
        self.assertEqual(catalog[1]["body"], "")
        self.assertEqual(catalog[2]["lessons"][0]["body"], "lesson")

    def test_chunking_preserves_full_source_and_overlap(self):
        class Tokenizer:
            def encode(self, text, **kwargs):
                return list(range(len(text.split())))

            def decode(self, tokens, **kwargs):
                return " ".join(map(str, tokens))

        item = {
            "entity_key": "article:a",
            "title": "x",
            "description": "",
            "topics": [],
            "tags": [],
            "industries": [],
            "body": " ".join(["x"] * 220),
        }
        units = make_units([item], Tokenizer(), window=96, overlap=16)
        body = [x for x in units if x["source"] == "body"]
        self.assertEqual([x["token_start"] for x in body], [0, 80, 160])
        self.assertEqual(len(body[-1]["text"].split()), 61)
        with self.assertRaises(ValueError):
            make_units([item], Tokenizer(), window=10, overlap=10)


class RetrievalTests(unittest.TestCase):
    def test_field_weight_changes_order_and_selection_cannot_inject(self):
        catalog = [
            {
                "entity_key": "article:a",
                "kind": "article",
                "title": "кофейня",
                "body": "",
                "description": "",
                "topics": ["бизнес"],
            },
            {
                "entity_key": "article:b",
                "kind": "article",
                "title": "кофейня",
                "body": "бизнес",
                "description": "",
                "topics": [],
            },
            {
                "entity_key": "article:c",
                "kind": "article",
                "title": "чужой",
                "body": "",
                "description": "",
                "topics": [],
            },
        ]
        index = FieldRetriever(catalog)
        signals = index.signals("кофейня бизнес", selected_keys=["article:c"])
        a = index.rank(signals, RankingConfig(topics=4, body=0), semantic=False)[0]
        b = index.rank(signals, RankingConfig(topics=0, body=4), semantic=False)[0]
        self.assertEqual(a[0], 0)
        self.assertEqual(b[0], 1)
        self.assertNotIn(2, a)

    def test_invalid_config(self):
        for params in [
            {"rrf_k": 0},
            {"title": float("nan")},
            {"selection_boost": 1.1},
            {"candidate_count": 1001},
        ]:
            with self.assertRaises(ValueError):
                RankingConfig(**params)
