import unittest

from scripts.audit_public_snapshot import audit


class PublicSnapshotAuditTests(unittest.TestCase):
    def test_slug_is_only_an_unverified_candidate(self):
        rows = [{'kind': 'course', 'entity_key': None, 'source_id': None, 'title': 'A',
                 'description': '', 'source_url': 'https://kurs.alfabank.ru/courses/slug/',
                 'access_type': 'unknown', 'price_status': 'unknown'}]
        report = audit(rows, [{'entity_key': 'course:1', 'kind': 'course', 'source_url': 'slug'}])
        self.assertEqual(report['by_kind']['course']['unverified_single_slug_candidate'], 1)
        self.assertNotIn('id_found_in_old_snapshot', report['by_kind']['course'])
        self.assertIsNone(rows[0]['entity_key'])

    def test_exact_identity_quality_and_conflicts(self):
        rows = [
            {'kind': 'course', 'entity_key': 'course:1', 'source_id': '1', 'title': 'A',
             'description': '', 'source_url': 'https://example/a', 'access_type': 'unknown',
             'price_status': 'unknown'},
            {'kind': 'course', 'entity_key': 'course:1', 'source_id': '1', 'title': 'B',
             'description': 'B', 'source_url': 'https://example/a', 'source_noindex_raw': True,
             'access_type': 'unknown', 'price_status': 'unknown'},
            {'kind': 'article', 'entity_key': None, 'source_id': None, 'title': 'C',
             'description': 'C', 'access_type': 'unknown', 'price_status': 'unknown'},
        ]
        report = audit(rows, [{'entity_key': 'course:1'}])
        self.assertEqual(report['records'], 3)
        self.assertEqual(report['by_kind']['course']['id_found_in_old_snapshot'], 2)
        self.assertEqual(report['by_kind']['article']['missing_id'], 1)
        self.assertEqual(report['repeated_entity_keys'], 1)
        self.assertEqual(report['conflicting_entity_keys'], 1)
        self.assertEqual(report['repeated_source_urls'], 1)
        self.assertFalse(report['coverage_verified'])


if __name__ == '__main__':
    unittest.main()
