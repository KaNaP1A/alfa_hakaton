import unittest

from alfa_reco.query_rules import exclusion_multiplier, intent_multiplier, plan_query
from alfa_reco.text import embedding_query, tokens


class QueryRulesTests(unittest.TestCase):
    def test_retaining_employees_is_disambiguated(self):
        for query in (
            "как удержать сотрудников",
            "удержание персонала",
            "как сохранить работников в команде",
        ):
            plan = plan_query(query)
            self.assertTrue(plan.retention_expansion, query)
            self.assertIn("мотивация", plan.retrieval_query)

    def test_deductions_are_not_mistaken_for_employee_retention(self):
        for query in (
            "как удержать алименты с выплаты сотруднику",
            "как удержать долг с зарплаты работника",
            "удержание налога из дохода сотрудников",
        ):
            self.assertFalse(plan_query(query).retention_expansion, query)

    def test_financial_titles_are_demoted_only_for_employee_retention(self):
        plan = plan_query("как удержать сотрудников")
        self.assertEqual(intent_multiplier("Как удержать алименты с выплаты сотруднику", plan), 0.2)
        self.assertEqual(intent_multiplier("Мотивация и зарплата сотрудников", plan), 1)
        plan = plan_query("как удержать алименты с выплаты сотруднику")
        self.assertEqual(intent_multiplier("Как удержать алименты с выплаты сотруднику", plan), 1)

    def test_contrast_reduces_negative_title_without_filtering_everything(self):
        for query in (
            "как удержать сотрудников, а не клиентов",
            "как удержать не клиентов, а сотрудников",
            "как удержать не клиентов а сотрудников",
        ):
            plan = plan_query(query)
            self.assertTrue(plan.contrast_applied, query)
            self.assertIn("клиент", plan.excluded_terms)
            self.assertNotIn("клиент", tokens(plan.retrieval_query))
            self.assertEqual(
                exclusion_multiplier(tokens("Как удержать клиентов"), plan.excluded_terms), 0.2
            )
            self.assertEqual(
                exclusion_multiplier(tokens("Почему сотрудники увольняются"), plan.excluded_terms),
                1,
            )

    def test_ambiguous_negation_is_reported_not_silently_parsed(self):
        for query in (
            "как не платить налог",
            "не только продажи но и маркетинг",
            "не только продажи, а также маркетинг",
        ):
            plan = plan_query(query)
            self.assertFalse(plan.contrast_applied, query)
            self.assertTrue(plan.unresolved_negation, query)
            self.assertEqual(plan.retrieval_query, query)

    def test_experience_and_price_are_explicitly_unverified(self):
        plan = plan_query("бесплатный курс по маркетингу без опыта")
        self.assertEqual(set(plan.unsupported_constraints), {"price", "experience"})
        self.assertNotIn("без опыта", plan.retrieval_query)
        self.assertNotIn("бесплатный", plan.retrieval_query)
        self.assertTrue(plan.unresolved_negation)
        self.assertEqual(plan_query("бесплатный").retrieval_query, "бесплатный")

    def test_short_keyword_permutations_and_negation(self):
        for first, second in [
            ("хочу открыть кофейню", "открыть кофейню хочу"),
            ("маркетинг для сотрудников", "сотрудников маркетинг"),
        ]:
            self.assertEqual(embedding_query(first), embedding_query(second))
            self.assertEqual(set(tokens(first)), set(tokens(second)))
        self.assertEqual(
            plan_query("не хочу открывать кофейню").retrieval_query, "не хочу открывать кофейню"
        )
        self.assertEqual(embedding_query("не хочу открывать кофейню"), "не хочу открывать кофейню")
        self.assertEqual(embedding_query("перевод денег от клиента"), "перевод денег от клиента")

    def test_debt_repayment_and_collection_are_not_confused(self):
        plan = plan_query("закрытие долгов")
        self.assertTrue(plan.debt_expansion)
        self.assertTrue(plan.debt_unspecified)
        self.assertIn("задолженность", plan.retrieval_query)
        self.assertFalse(plan_query("как взыскать долг с клиента").debt_expansion)
        self.assertFalse(plan_query("погасить налоговую задолженность").debt_unspecified)
        self.assertEqual(intent_multiplier("Как взыскать долг с контрагента", plan), 0.2)
        self.assertEqual(intent_multiplier("Дебиторская задолженность", plan), 0.2)
        collection = plan_query("как взыскать долг с клиента")
        self.assertEqual(intent_multiplier("Как взыскать долг с контрагента", collection), 1)

    def test_exclusion_does_not_remove_shared_positive_word(self):
        plan = plan_query("сотрудники отдела продаж, а не сотрудники отдела поддержки")
        self.assertNotIn("сотрудник", plan.excluded_terms)
        self.assertIn("поддержк", plan.excluded_terms)


if __name__ == "__main__":
    unittest.main()
