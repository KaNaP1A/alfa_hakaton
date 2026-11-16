import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np

from evaluate_natural_review import scored_metrics
from import_natural_human_review import parse_review
from train_relevance import prepare_training, weak_queries


class NaturalReviewTests(unittest.TestCase):
    def test_pool_metric_does_not_invent_relevance_for_unknown_candidates(self):
        labels = {'a': 3, 'b': 0, 'c': 2}
        best = scored_metrics(['a', 'c', 'b'], labels)
        worse = scored_metrics(['b', 'c', 'a'], labels)
        self.assertAlmostEqual(best['ndcg5'], 1.0)
        self.assertGreater(best['ndcg5'], worse['ndcg5'])
        self.assertIsNone(scored_metrics(['a', 'b'], {'a': 1, 'b': 0}))

    def test_human_import_skips_unknowns_and_checks_exact_pool(self):
        pool = [{'id': 'n01', 'candidates': [{'entity_key': 'a'}, {'entity_key': 'b'}]}]
        text = ('## n01 — запрос\n- Оценка человека: 2 — **Первый** (`a`)\n'
                '- Оценка человека: ? — **Второй** (`b`)\n')
        rows = parse_review(text, pool)
        self.assertEqual([(r['entity_key'], r['grade']) for r in rows], [('a', 2)])
        self.assertFalse(rows[0]['human_verified'])
        with self.assertRaisesRegex(ValueError, 'Missing candidate'):
            parse_review(text.splitlines()[0] + '\n' + text.splitlines()[1], pool)
        with self.assertRaisesRegex(ValueError, 'Unknown or duplicate'):
            parse_review(text.replace('`b`', '`a`'), pool)

    def test_weak_automatic_sources_exclude_heldout(self):
        catalog = [{'entity_key': 'article:keep', 'title': 'Материал номер один', 'kind': 'article'},
                   {'entity_key': 'article:heldout', 'title': 'Материал номер два', 'kind': 'article'}]
        with patch('train_relevance.eligible_sources', return_value=catalog), \
             patch('train_relevance.title_candidates', return_value=[('short_fragment', 'search', 'достаточно длинный запрос')]), \
             patch('train_relevance.description_candidate', return_value=None):
            rows = weak_queries(catalog, [], None, limit=10, exclude_ids={'article:heldout'})
        self.assertTrue(rows)
        self.assertEqual({r['target'] for r in rows}, {'article:keep'})

    def test_local_weak_sources_cannot_reference_heldout(self):
        catalog = [{'entity_key': 'article:heldout', 'title': 'Материал номер два', 'kind': 'article'}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'queries.jsonl'
            path.write_text(json.dumps({'target': 'article:heldout', 'query': 'пример запроса', 'split': 'train'})+'\n')
            with patch('train_relevance.eligible_sources', return_value=catalog):
                with self.assertRaisesRegex(ValueError, 'protected split'):
                    weak_queries(catalog, [], path, exclude_ids={'article:heldout'})

    def test_provisional_training_excludes_heldout_documents(self):
        catalog = [{'entity_key': key} for key in ('heldout', 'positive', 'negative')]
        backend = SimpleNamespace(engine=SimpleNamespace(catalog=catalog),
                                  prepare=lambda query: {'features': np.zeros((3, 2))})
        cases = [{'id': 'a', 'family': 'family', 'query': 'запрос', 'split': 'train',
                  'judgments': [{'entity_key': 'heldout', 'grade': 3},
                                {'entity_key': 'positive', 'grade': 2},
                                {'entity_key': 'negative', 'grade': 0}]}]
        with tempfile.TemporaryDirectory() as tmp:
            groups = prepare_training(backend, cases, [], Path(tmp),
                                      provisional_exclude_ids={'heldout'})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['entity_keys'], ['positive', 'negative'])

if __name__=='__main__': unittest.main()
