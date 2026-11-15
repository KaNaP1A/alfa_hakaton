import json
import unittest

from scripts.extract_public_angular_state import extract


def page(items, count=1, endpoint='/api/public/courses/glossary/list'):
    state = {'list': {'u': 'https://kurs.alfabank.ru' + endpoint, 'b': items},
             'count': {'u': 'https://kurs.alfabank.ru' + endpoint + '/count', 'b': count}}
    return '<html><script id="ng-state" type="application/json">' + json.dumps(state, ensure_ascii=False) + '</script></html>'


class PublicAngularStateTests(unittest.TestCase):
    def test_extract_preserves_unknown_rights_and_source(self):
        item = {'id': 'id-1', 'title': 'Пример', 'url': 'primer', 'description': 'Текст',
                'statusId': 'a', 'published': None, 'noIndex': False}
        rows, report = extract(page([item]), 'vocabulary', 'https://kurs.alfabank.ru/vocabulary/', 'now')
        self.assertEqual(rows[0]['entity_key'], 'glossary:id-1')
        self.assertEqual(rows[0]['access_type'], 'unknown')
        self.assertEqual(rows[0]['price_status'], 'unknown')
        self.assertIsNone(rows[0]['canonical_url'])
        self.assertTrue(report['list_matches_reported_count'])
        self.assertEqual(report['missing_publication_dates'], 1)
        self.assertFalse(report['coverage_verified'])

    def test_mismatch_is_reported_not_hidden(self):
        item = {'id': 'id-1', 'title': 'Пример', 'url': 'primer'}
        _, report = extract(page([item], 2), 'vocabulary', 'https://kurs.alfabank.ru/vocabulary/', 'now')
        self.assertFalse(report['list_matches_reported_count'])

    def test_invalid_source_and_duplicate_ids_fail(self):
        item = {'id': 'id-1', 'title': 'Пример', 'url': 'primer'}
        with self.assertRaises(ValueError):
            extract(page([item]), 'vocabulary', 'https://other.example/vocabulary/', 'now')
        with self.assertRaises(ValueError):
            extract(page([item, item], 2), 'vocabulary', 'https://kurs.alfabank.ru/vocabulary/', 'now')
        with self.assertRaises(ValueError):
            extract('<html></html>', 'vocabulary', 'https://kurs.alfabank.ru/vocabulary/', 'now')


if __name__ == '__main__':
    unittest.main()
