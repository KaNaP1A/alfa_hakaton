import math
import unittest
from datetime import UTC, datetime

from alfa_reco.commercial_experiment import eligible, features, rerank_synthetic_only

NOW = datetime(2026, 11, 15, tzinfo=UTC)


def offer(n, **changes):
    return {'entity_key': f'course:{n}', 'offer_id': f'offer:{n}', 'kind': 'course',
            'price_minor': 100000 * (n + 1), 'currency': 'RUB', 'verified': True,
            'purchasable': True, 'owned': False, 'valid_until': '2026-12-01T00:00:00Z', **changes}


class Model:
    def __init__(self, values):
        self.values = values

    def predict_proba(self, rows):
        return [[1 - p, p] for p in self.values[:len(rows)]]


class CommercialExperimentTests(unittest.TestCase):
    def test_rejects_unknown_stale_owned_free_unverified_and_wrong_currency(self):
        self.assertTrue(eligible(offer(0), NOW))
        for changes in ({'verified': False}, {'owned': True}, {'owned': None},
                        {'purchasable': False}, {'price_minor': 0}, {'price_minor': True},
                        {'price_minor': None}, {'currency': 'USD'}, {'kind': 'article'},
                        {'valid_until': '2026-11-01T00:00:00Z'}, {'valid_until': 'bad'},
                        {'valid_until': '2026-12-01T00:00:00'}):
            with self.subTest(changes=changes):
                self.assertFalse(eligible(offer(0, **changes), NOW))

    def test_filter_explicit_maximum_and_never_invent_budget(self):
        result = rerank_synthetic_only([offer(0), offer(1)], Model([0.5]), now=NOW,
                                       max_price_minor=150000)
        self.assertEqual([row['offer_id'] for row in result['results']], ['offer:0'])
        self.assertEqual(features(0, 1, 100000)[2:], [0.0, 0.0, 0.0])
        empty = rerank_synthetic_only([offer(0)], Model([]), now=NOW, max_price_minor=1)
        self.assertEqual(empty['status'], 'no_offers_within_budget')
        with self.assertRaises(ValueError):
            features(0, 1, 100000, 0)

    def test_price_reranking_moves_no_item_more_than_one_place(self):
        items = [offer(i) for i in range(4)]
        result = rerank_synthetic_only(items, Model([0.01, 0.99, 0.01, 0.99]), now=NOW)
        self.assertTrue(result['synthetic_only'])
        self.assertEqual([o['offer_id'] for o in result['results']], ['offer:1', 'offer:0', 'offer:3', 'offer:2'])
        self.assertTrue(all(abs(i + 1 - item['original_position']) <= 1
                            for i, item in enumerate(result['results'])))
        self.assertNotIn('synthetic_commercial_signal', items[0])

    def test_invalid_model_and_duplicates(self):
        with self.assertRaises(ValueError):
            rerank_synthetic_only([offer(0), offer(0)], Model([0.2, 0.3]), now=NOW)
        with self.assertRaises(ValueError):
            rerank_synthetic_only([offer(0)], Model([math.nan]), now=NOW)

    def test_unverified_offers_never_reach_the_model(self):
        class ForbiddenModel:
            def predict_proba(self, rows):
                raise AssertionError('Model should not receive unverified offers')

        result = rerank_synthetic_only([offer(0, verified=False), offer(1, owned=True)],
                                       ForbiddenModel(), now=NOW)
        self.assertEqual(result['status'], 'no_verified_offers')
        self.assertEqual(result['results'], [])

    def test_price_equal_to_user_limit_is_allowed(self):
        result = rerank_synthetic_only([offer(0), offer(1)], Model([0.5]), now=NOW,
                                       max_price_minor=100000)
        self.assertEqual([row['offer_id'] for row in result['results']], ['offer:0'])

    def test_offer_expires_at_its_deadline_and_must_use_timezone(self):
        self.assertFalse(eligible(offer(0, valid_until='2026-11-15T00:00:00Z'), NOW))
        self.assertTrue(eligible(offer(0, valid_until='2026-11-15T00:00:01Z'), NOW))
        self.assertFalse(eligible(offer(0), NOW.replace(tzinfo=None)))

    def test_equal_offers_keep_original_order_and_do_not_mutate_input(self):
        offers = [offer(0), offer(1, price_minor=100000)]
        original = [dict(row) for row in offers]
        result = rerank_synthetic_only(offers, Model([0.5, 0.5]), now=NOW)
        self.assertEqual([row['offer_id'] for row in result['results']], ['offer:0', 'offer:1'])
        self.assertEqual(offers, original)

    def test_invalid_budgets_limits_and_prediction_counts_are_rejected(self):
        for value in (0, -1, True, 1.5):
            with self.subTest(budget=value), self.assertRaises(ValueError):
                rerank_synthetic_only([offer(0)], Model([0.5]), now=NOW, budget_minor=value)
            with self.subTest(max_price=value), self.assertRaises(ValueError):
                rerank_synthetic_only([offer(0)], Model([0.5]), now=NOW, max_price_minor=value)
        for value in (-0.01, 1.01):
            with self.subTest(min_gap=value), self.assertRaises(ValueError):
                rerank_synthetic_only([offer(0)], Model([0.5]), now=NOW, min_gap=value)
        with self.assertRaises(ValueError):
            rerank_synthetic_only([offer(0), offer(1)], Model([0.5]), now=NOW)


if __name__ == '__main__':
    unittest.main()
