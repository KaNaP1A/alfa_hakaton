import unittest

import numpy as np

from scripts.train_mixed_catalog_simulation import arrays, sample_sessions, split_catalog


class MixedCatalogSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [{'entity_key': f'article:{i}', 'title': f'Тема {i}',
                         'kind': 'article', 'access_type': 'unknown'} for i in range(60)]
        self.catalog += [{'entity_key': 'article:duplicate', 'title': 'Тема 0',
                          'kind': 'article', 'access_type': 'unknown'}]
        rng = np.random.default_rng(11)
        self.vectors = rng.normal(size=(len(self.catalog), 384)).astype(np.float32)
        self.vectors /= np.linalg.norm(self.vectors, axis=1, keepdims=True)

    def test_split_keeps_same_kind_and_normalized_title_together(self):
        splits = split_catalog(self.catalog)
        self.assertEqual(sum(map(len, splits.values())), len(self.catalog))
        location = {index: name for name, indices in splits.items() for index in indices}
        self.assertEqual(location[0], location[60])
        self.assertEqual(len(set(location)), len(self.catalog))

    def test_simulated_offers_and_unexamined_labels_are_explicit(self):
        rows = sample_sessions(self.catalog, self.vectors, list(range(len(self.catalog))), 20, 7)
        self.assertEqual(len(rows), 200)
        self.assertTrue(all(row['synthetic'] for row in rows))
        self.assertTrue(all(row['engaged'] is None and row['purchased'] is None
                            for row in rows if not row['examined']))
        self.assertTrue(all(not row['purchased'] or row['engaged'] for row in rows if row['examined']))
        self.assertEqual({row['synthetic_offer_state'] for row in rows}, {'free', 'paid', 'subscription'})
        self.assertTrue(all(row['synthetic_price_rub'] == 0 for row in rows
                            if row['synthetic_offer_state'] == 'free'))
        x, y = arrays(rows, 'purchased')
        self.assertEqual(len(x), sum(row['examined'] for row in rows))
        self.assertEqual(len(x), len(y))
        self.assertTrue(all(row['snapshot_access'] == 'unknown' for row in rows))


if __name__ == '__main__':
    unittest.main()
