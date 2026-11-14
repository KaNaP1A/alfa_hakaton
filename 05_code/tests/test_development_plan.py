import unittest

from test_suggestions import material

from alfa_reco.development_plan import development_plan


class DevelopmentPlanTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            material('course:base', 'Управление командой сотрудников', ['Управление командой']),
            material('course:next', 'Мотивация сотрудников команды', ['Управление командой']),
            material('webinar:next', 'Удержание сотрудников команды', ['Управление командой']),
            material('document:next', 'План развития сотрудников команды', ['Управление командой']),
            material('article:other', 'Налоги кофейни', ['Финансы']),
        ]

    def plan(self, viewed=(), completed=(), categories=()):
        return development_plan(self.catalog, list(categories), list(viewed), list(completed))

    def test_completion_has_grounded_steps_and_excludes_history(self):
        plan = self.plan(completed=['course:base'])
        self.assertEqual(plan['status'], 'ready')
        for step in plan['steps']:
            self.assertNotEqual(step['material']['entity_key'], 'course:base')
            self.assertEqual(step['evidence']['entity_key'], 'course:base')
            self.assertEqual(step['evidence']['signal'], 'completed')
            self.assertIn('Управление командой', step['why'])
            self.assertNotEqual(step['material']['entity_key'], 'article:other')

    def test_view_does_not_claim_completion(self):
        plan = self.plan(viewed=['course:base'])
        self.assertTrue(plan['steps'])
        self.assertEqual(plan['steps'][0]['evidence']['signal'], 'viewed')
        self.assertNotIn('завершённым', plan['steps'][0]['why'])

    def test_duplicates_do_not_change_plan(self):
        self.assertEqual(self.plan(completed=['course:base']), self.plan(completed=['course:base'] * 5))

    def test_completion_wins_over_view_for_same_item(self):
        self.assertEqual(self.plan(completed=['course:base']),
                         self.plan(completed=['course:base'], viewed=['course:base']))

    def test_no_activity_and_no_related_candidates(self):
        self.assertEqual(self.plan(categories=['team'])['status'], 'needs_activity')
        self.assertEqual(self.plan(viewed=['article:other'])['status'], 'insufficient_evidence')

    def test_partial_plan_and_all_history_are_excluded(self):
        p = self.plan(completed=['course:base', 'course:next'], viewed=['webinar:next'])
        self.assertEqual(p['status'], 'partial')
        self.assertEqual([s['material']['entity_key'] for s in p['steps']], ['document:next'])

    def test_unknown_and_noncourse_completion_are_rejected(self):
        for completed in (['missing'], ['document:next'], [None]):
            with self.assertRaises(ValueError):
                self.plan(completed=completed)
        with self.assertRaises(ValueError):
            development_plan(self.catalog, [], 'course:base', [])

    def test_equivalent_title_not_recommended_again(self):
        self.catalog.append(material('course:duplicate', 'Управление командой сотрудников', ['Управление командой']))
        self.assertNotIn('course:duplicate', [s['material']['entity_key'] for s in self.plan(completed=['course:base'])['steps']])

    def test_generic_steps_and_models_do_not_create_a_learning_path(self):
        c = [material('course:lbo', 'Модель LBO шаг за шагом', ['Финансы']),
             material('article:contract', 'Договор оказания услуг шаг за шагом', ['Законы']),
             material('article:franchise', 'Как выбрать работающую модель франшизы', ['Бизнес'])]
        self.assertEqual(development_plan(c, [], [], ['course:lbo'])['steps'], [])
