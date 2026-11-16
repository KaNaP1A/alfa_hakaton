import unittest

from scripts.build_offline_mixed_index import merge_snapshot


def old(key):
    return {'entity_key': key, 'kind': 'article', 'title': 'Existing'}


def item(identity='public:1', origin='public_snapshot', source_id='1', kind='article'):
    return {'id': identity, 'origin': origin, 'source_id': source_id, 'kind': kind,
            'title': 'Title', 'description': 'Description', 'topics': ['Тема'],
            'price': {'status': 'fictional', 'amount': 1000}, 'source_url': 'https://example.org'}


class OfflineMixedIndexTests(unittest.TestCase):
    def test_exact_id_retains_original_and_unmatched_is_unverified(self):
        base = [old('article:1')]
        result, counts = merge_snapshot(base, [item(), item('public:2', source_id='2')])
        self.assertEqual(result[0], base[0])
        self.assertEqual(len(result), 2)
        self.assertEqual(counts['retained_baseline_exact_id'], 1)
        added = result[1]
        self.assertTrue(added['entity_key'].startswith('article:offline-'))
        self.assertEqual(added['topics'], [])
        self.assertIsNone(added['canonical_url'])
        self.assertIsNone(added['price_raw'])
        self.assertEqual(added['access_type'], 'unknown')

    def test_synthetic_price_never_becomes_real_catalog_fact(self):
        result, _ = merge_snapshot([], [item('synthetic:course:1', 'synthetic', None, 'course')])
        row = result[0]
        self.assertEqual(row['topics'], ['Тема'])
        self.assertIsNone(row['price_raw'])
        self.assertEqual(row['experiment_origin'], 'synthetic')
        self.assertEqual(row['publication_status'], 'unknown')

    def test_determinism_and_invalid_ids(self):
        items = [item('a', source_id='2'), item('b', source_id='3')]
        self.assertEqual(merge_snapshot([], items), merge_snapshot([], list(reversed(items))))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            merge_snapshot([], [item(), item()])
        with self.assertRaises(ValueError):
            merge_snapshot([], [item(origin='unknown')])

    def test_restored_backup_is_not_duplicated_and_lessons_are_demo_only(self):
        base = [{'entity_key': 'webinar:1', 'kind': 'webinar', 'title': 'Вебинар'}]
        restored = {'id': 'historical:webinar:1', 'origin': 'historical_backup',
                    'kind': 'webinar', 'historical_entity_key': 'webinar:1'}
        lesson = {'id': 'synthetic:lesson:1', 'origin': 'synthetic', 'kind': 'lesson'}
        result, counts = merge_snapshot(base, [restored, lesson])
        self.assertEqual(result, base)
        self.assertEqual(counts['retained_historical_exact_id'], 1)
        self.assertEqual(counts['excluded_synthetic_lesson_unsupported'], 1)
        with self.assertRaisesRegex(ValueError, 'does not match baseline'):
            merge_snapshot([], [restored])


if __name__ == '__main__':
    unittest.main()
