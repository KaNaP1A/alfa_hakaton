import json
import unittest

from scripts.extract_related_course_ids import extract

BASE = 'https://kurs.alfabank.ru'
ID1 = '11111111-1111-4111-8111-111111111111'
ID2 = '22222222-2222-4222-8222-222222222222'


def page(items):
    state = {'x': {'u': BASE + '/api/public/courses/list?take=3', 'b': items}}
    return '<script id="ng-state">' + json.dumps(state) + '</script>'


class RelatedCourseIdTests(unittest.TestCase):
    def test_exact_slug_keeps_identity_unverified_and_private_fields_out(self):
        inventory = [{'url': BASE + '/courses/example/', 'kind_hint': 'course', 'robots_allowed': True}]
        item = {'id': ID1, 'url': 'example', 'title': 'Example', 'isPaid': True,
                'users': [{'secret': 'NEVER_STORE'}]}
        rows, report = extract([(BASE + '/documents/a/', page([item]))], inventory)
        self.assertEqual(report['matched_course_urls'], 1)
        self.assertEqual(rows[0]['source_id'], ID1)
        self.assertFalse(rows[0]['backend_identity_verified'])
        self.assertFalse(rows[0]['current_price_verified'])
        self.assertNotIn('NEVER_STORE', json.dumps(rows))

    def test_conflicting_ids_and_reused_id_are_not_merged(self):
        inventory = [{'url': BASE + '/courses/a/', 'kind_hint': 'course', 'robots_allowed': True},
                     {'url': BASE + '/courses/b/', 'kind_hint': 'course', 'robots_allowed': True}]
        items = [{'id': ID1, 'url': 'a', 'title': 'A'}, {'id': ID2, 'url': 'a', 'title': 'A'},
                 {'id': ID1, 'url': 'b', 'title': 'B'}]
        rows, report = extract([(BASE + '/documents/a/', page(items))], inventory)
        self.assertEqual(len(rows), 1)
        self.assertEqual(report['errors']['conflicting_ids'], 1)
        items = [{'id': ID1, 'url': 'a', 'title': 'A'}, {'id': ID1, 'url': 'b', 'title': 'B'}]
        rows, report = extract([(BASE + '/documents/a/', page(items))], inventory)
        self.assertFalse(rows)
        self.assertEqual(report['errors']['id_matches_multiple_urls'], 1)


if __name__ == '__main__':
    unittest.main()
