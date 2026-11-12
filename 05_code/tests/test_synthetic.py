import json
import tempfile
import unittest
from pathlib import Path

from alfa_reco.synthetic import (
    build_dataset,
    description_candidate,
    normalize,
    protected_from_files,
    review_sample,
    split_for,
    sufficiently_distinct_topics,
    typo,
)


def item(source, title, kind="article", description=""):
    return {
        "entity_key": source,
        "title": title,
        "kind": kind,
        "description": description,
        "topics": ["Управление командой"],
        "tags": ["Продажи"],
    }


class SyntheticTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            item(
                "article:a",
                "Как открыть кофейню",
                description="Расскажем как выбрать помещение и рассчитать расходы",
            ),
            item("article:b", "Как выбрать помещение"),
            item("course:c", "Как управлять командой", "course"),
        ]

    def test_seed_reproducible_and_catalog_order_independent(self):
        first, stats = build_dataset(self.catalog, 42)
        second, same_stats = build_dataset(list(reversed(self.catalog)), 42)
        self.assertEqual(first, second)
        self.assertEqual(stats, same_stats)
        self.assertNotEqual(first, build_dataset(self.catalog, 43)[0])
        self.assertEqual(review_sample(first, 42, 10), review_sample(second, 42, 10))

    def test_no_labels_duplicate_queries_or_leakage_by_source_and_family(self):
        rows, _ = build_dataset(self.catalog)
        self.assertTrue(rows)
        query_keys = [normalize(row["query"]) for row in rows]
        self.assertEqual(len(query_keys), len(set(query_keys)))
        by_source, by_group = {}, {}
        for row in rows:
            self.assertIsNone(row["relevance"])
            if row["source_id"]:
                self.assertEqual(row["label_status"], "weak_source_reference")
                by_source.setdefault(row["source_id"], set()).add(row["split"])
            else:
                self.assertEqual(row["label_status"], "unjudged")
            by_group.setdefault(row["group_id"], set()).add(row["split"])
        self.assertTrue(all(len(values) == 1 for values in by_source.values()))
        self.assertTrue(all(len(values) == 1 for values in by_group.values()))
        self.assertEqual(set(by_source), {"article:a", "article:b", "course:c"})

    def test_protected_ids_titles_and_queries_are_excluded(self):
        rows, _ = build_dataset(
            self.catalog,
            protected_ids={"article:a"},
            protected_titles={normalize("Как управлять командой")},
            protected_queries={normalize("Как выбрать помещение")},
        )
        self.assertFalse(any(row["source_id"] in {"article:a", "course:c"} for row in rows))
        self.assertFalse(any(normalize(row["query"]) == "как выбрать помещение" for row in rows))

    def test_similar_titles_share_group_and_split(self):
        catalog = [item("article:a", "Ёлка для бизнеса"), item("article:b", "елка для бизнеса")]
        rows, _ = build_dataset(catalog)
        related = [row for row in rows if row["source_id"]]
        self.assertEqual(len({row["group_id"] for row in related}), 1)
        self.assertEqual(len({row["split"] for row in related}), 1)

    def test_protected_id_also_excludes_duplicate_catalog_title(self):
        catalog = [
            item("article:a", "Как открыть кофейню"),
            item("article:b", "Как открыть кофейню"),
        ]
        rows, _ = build_dataset(catalog, protected_ids={"article:a"})
        self.assertFalse(any(row["source_id"] in {"article:a", "article:b"} for row in rows))

    def test_nearly_identical_titles_are_grouped(self):
        catalog = [
            item("article:a", "ИП на НПД в 2026 году расчёт и сроки уплаты налогов"),
            item("article:b", "ИП на ПСН в 2026 году расчёт и сроки уплаты налогов"),
        ]
        rows, _ = build_dataset(catalog)
        groups = {row["group_id"] for row in rows if row["source_id"]}
        self.assertEqual(len(groups), 1)

    def test_out_of_domain_is_not_a_negative_label(self):
        rows, _ = build_dataset(self.catalog)
        probes = [row for row in rows if row["scenario"] == "out_of_domain_unjudged"]
        self.assertGreater(len(probes), 0)
        self.assertTrue(
            all(row["relevance"] is None and row["source_id"] is None for row in probes)
        )

    def test_complex_scenarios_are_unjudged_and_grouped_by_family(self):
        rows, _ = build_dataset(self.catalog)
        complex_rows = [row for row in rows if row["scenario"] == "complex_situation_unjudged"]
        self.assertGreaterEqual(len(complex_rows), 250)
        groups = {}
        for row in complex_rows:
            self.assertIsNone(row["relevance"])
            self.assertIsNone(row["source_id"])
            groups.setdefault(row["group_id"], set()).add(row["split"])
        self.assertTrue(all(len(splits) == 1 for splits in groups.values()))

    def test_typo_is_one_adjacent_swap_and_stable(self):
        original = "открытие кофейни"
        altered = typo(original, 42)
        self.assertEqual(altered, typo(original, 42))
        self.assertNotEqual(original, altered)
        self.assertEqual(sorted(original), sorted(altered))
        self.assertEqual(sum(a != b for a, b in zip(original, altered, strict=True)), 2)
        self.assertIsNone(typo("ИП", 42))

    def test_contrasted_topics_do_not_share_a_stem(self):
        self.assertFalse(sufficiently_distinct_topics("Финансовый анализ", "Финансы и учет"))
        self.assertTrue(sufficiently_distinct_topics("Маркетинг", "Налоги и законы"))

    def test_description_is_a_weak_text_fragment_not_a_judgment(self):
        phrase = description_candidate(self.catalog[0])
        self.assertTrue(phrase.startswith("Интересует:"))
        self.assertIn("рассчитать расходы", phrase)
        self.assertIsNone(
            description_candidate(item("x", "Тема", description="см. https://example.com"))
        )

    def test_load_protected_and_stable_split(self):
        fixture = {
            "queries": [{"query": "Ёлка", "judgments": [{"entity_key": "x", "title": "Тема"}]}]
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "gold.json"
            path.write_text(json.dumps(fixture), encoding="utf-8")
            ids, titles, queries = protected_from_files([path])
        self.assertEqual(ids, {"x"})
        self.assertEqual(titles, {"тема"})
        self.assertEqual(queries, {"елка"})
        self.assertEqual(split_for("group", 7), split_for("group", 7))


if __name__ == "__main__":
    unittest.main()
