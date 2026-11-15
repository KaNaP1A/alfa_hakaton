import unittest

from scripts.train_commercial_simulation import make_sessions, training_rows


class SimulatorTests(unittest.TestCase):
    def test_seeded_sessions_random_prices_and_unexamined_are_not_negatives(self):
        courses = [{'title': 'Учебный пример', 'category': 'A'},
                   {'title': 'Другой пример', 'category': 'B'}]
        sessions = make_sessions(courses, 100, 123, 'base')
        repeated = make_sessions(courses, 100, 123, 'base')
        self.assertEqual(sessions, repeated)
        rows, labels, records = training_rows(sessions, 99)
        self.assertEqual(len(records), 200)
        self.assertEqual(len(rows), sum(row['examined'] for row in records))
        self.assertEqual(len(rows), len(labels))
        self.assertTrue(all(r['purchase'] is None for r in records if not r['examined']))
        self.assertTrue(all(isinstance(r['purchase'], bool) for r in records if r['examined']))
        prices = {c['price_minor'] for session in sessions for c in session['candidates']
                  if c['entity_key'] == 'course:synthetic-0'}
        self.assertGreater(len(prices), 2)
        self.assertTrue(all(r['synthetic'] for r in records))


if __name__ == '__main__':
    unittest.main()
