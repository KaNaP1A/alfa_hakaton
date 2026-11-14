import unittest
from unittest.mock import patch

from alfa_reco.cli import normalize
from alfa_reco.verified_links import apply_verified_links


class CatalogTests(unittest.TestCase):
    def test_only_individually_verified_slug_and_kind_get_link(self):
        items = [
            {
                "kind": "calculator",
                "source_url": "ndfl",
                "canonical_url": None,
                "data_quality_flags": ["url_unverified"],
                "provenance": {},
            },
            {
                "kind": "article",
                "source_url": "ndfl",
                "canonical_url": None,
                "data_quality_flags": ["url_unverified"],
                "provenance": {},
            },
        ]
        apply_verified_links(items)
        self.assertEqual(items[0]["canonical_url"], "https://kurs.alfabank.ru/calculators/ndfl/")
        self.assertEqual(items[0]["data_quality_flags"], [])
        self.assertIsNone(items[1]["canonical_url"])

    def test_calculator_requires_one_published_live_page_with_same_id(self):
        source = {
            "Statuses": [{"Id": "pub", "Title": "Опубликовано"}],
            "CourseTypes": [],
            "ContentSettings": [],
            "Topics": [],
            "Tags": [],
            "Industries": [],
            "ContentSettingsTopics": [],
            "ContentSettingsTags": [],
            "ContentSettingsIndustries": [],
            "Calculators": [
                {"Id": x, "Title": x, "IsDeleted": "f"}
                for x in ("ok", "missing", "deleted", "duplicate")
            ],
            "CalculatorPages": [
                {"Id": "ok", "StatusId": "pub", "IsDeleted": "f"},
                {"Id": "deleted", "StatusId": "pub", "IsDeleted": "t"},
                *[{"Id": "duplicate", "StatusId": "pub", "IsDeleted": "f"}] * 2,
            ],
        }
        with (
            patch("alfa_reco.cli.KINDS", {"Calculators": "calculator"}),
            patch("alfa_reco.cli.rows", side_effect=lambda c, t: source[t]),
        ):
            catalog, excluded = normalize(None)
        self.assertEqual([x["source_id"] for x in catalog], ["ok"])
        self.assertEqual(excluded["calculator:publication_unknown_or_not_published"], 3)
