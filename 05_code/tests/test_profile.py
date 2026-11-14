import copy
import unittest
from unittest.mock import patch

from test_suggestions import material

from alfa_reco.profile import development_plan_for_profile, recommend_for_profile, validate_profile
from alfa_reco.profile_metadata import experience_evidence, industry_matches, stage_evidence


class Engine:
    generation = "generation-one"

    def __init__(self):
        self.catalog = [
            material("course:base", "Управление командой сотрудников", ["Управление командой"]),
            material("course:next", "Мотивация сотрудников команды", ["Управление командой"]),
            material("webinar:next", "Удержание сотрудников команды", ["Управление командой"],
                     industries=["Торговля"]),
            material("document:next", "План развития сотрудников команды", ["Управление командой"]),
            material("article:tax", "Налоги кофейни", ["Финансы"]),
        ]
        self.answer = [dict(self.catalog[1]), dict(self.catalog[2]), dict(self.catalog[4])]
        self.calls = []
        self.metadata = {"confidence": {"status": "unvalidated"}, "alternatives": []}

    def search(self, query, *, mode, top, **kwargs):
        self.calls.append((query, mode, top))
        self.last_options = kwargs
        return {"results": copy.deepcopy(self.answer), **copy.deepcopy(self.metadata)}


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()
        self.base = {"generation": self.engine.generation}

    def test_goal_search_is_boundary_and_exact_metadata_preferences_reorder(self):
        self.engine.metadata["request_understanding"] = {"format": "webinar", "method": "narrow_rules_v1"}
        self.engine.metadata["retrieval_diagnostics"] = {"retrieved_candidates": 10}
        result = recommend_for_profile(self.engine, {
            **self.base, "goal": "управление командой", "industry": "торговля",
            "preferred_kinds": ["webinar"],
        })
        self.assertEqual(self.engine.calls, [("управление командой", "relevance", 50)])
        self.assertEqual(result["results"][0]["entity_key"], "webinar:next")
        self.assertTrue(result["results"][0]["profile_evidence"]["industry"])
        self.assertTrue(result["results"][0]["profile_evidence"]["preferred_kind"])
        self.assertEqual(result["results"][0]["profile_evidence"]["goal_rank"], 2)
        self.assertEqual(result["goal_search"]["request_understanding"]["format"], "webinar")
        self.assertEqual(result["goal_search"]["retrieval_diagnostics"]["retrieved_candidates"], 10)
        self.assertTrue({x["entity_key"] for x in result["results"]} <= {
            x["entity_key"] for x in self.engine.answer
        })

    def test_focus_is_an_explicit_filter_for_goal_history_and_plan(self):
        profile = {
            **self.base, "goal": "команда", "categories": ["team"],
            "focus_facet": "Управление командой",
            "events": [{"entity_key": "course:base", "action": "completed"}],
        }
        result = recommend_for_profile(self.engine, profile)
        self.assertTrue(result["results"])
        self.assertNotIn("article:tax", [item["entity_key"] for item in result["results"]])
        self.assertEqual(result["profile_usage"]["focus_facet"], "strict_catalog_facet_filter")
        plan = development_plan_for_profile(self.engine, profile)
        self.assertTrue(plan["steps"])
        self.assertTrue(all("Управление командой" in step["material"]["topics"]
                            for step in plan["steps"]))

    def test_region_is_not_claimed_to_affect_goal_or_history(self):
        result = recommend_for_profile(self.engine, {**self.base, "goal": "команда", "region": "Москва"})
        self.assertEqual(result["profile_usage"]["region"], "not_used_for_goal_or_history")

    def test_stage_and_experience_are_accepted_but_never_fabricated(self):
        plain = recommend_for_profile(self.engine, {**self.base, "goal": "команда"})
        with_profile = recommend_for_profile(self.engine, {
            **self.base, "goal": "команда", "business_stage": "launch", "experience": "beginner",
        })
        self.assertEqual(plain["results"], with_profile["results"])
        self.assertEqual(with_profile["profile_usage"]["business_stage"], "no_catalog_match")
        self.assertEqual(with_profile["profile_usage"]["experience"], "no_catalog_match")

    def test_source_facts_enable_limited_stage_and_experience_preferences(self):
        course = self.engine.catalog[1]
        course.update(source_table="Courses", target_audience="Вы только начинаете бизнес",
                      industries=["Без опыта"])
        self.engine.answer = [dict(course), dict(self.engine.catalog[2])]
        result = recommend_for_profile(self.engine, {
            **self.base, "goal": "команда", "business_stage": "launch", "experience": "beginner",
        })
        self.assertEqual(result["profile_usage"]["business_stage"], "used_when_source_matched")
        self.assertEqual(result["profile_usage"]["experience"], "used_when_source_matched")
        evidence = result["results"][0]["profile_evidence"]
        self.assertEqual(evidence["business_stage"]["source"], "target_audience")
        self.assertEqual(evidence["experience"]["source"], "industries")
        self.assertIsNone(experience_evidence("advanced", course))
        experienced = {**course, "industries": ["С опытом"]}
        self.assertIsNotNone(experience_evidence("intermediate", experienced))
        self.assertIsNotNone(experience_evidence("advanced", experienced))
        self.assertIsNone(experience_evidence("beginner", experienced))
        self.assertIsNone(stage_evidence("operating", course))
        self.assertIsNone(stage_evidence("launch", {**course, "target_audience": "Вы не начинаете бизнес"}))
        self.assertIsNone(stage_evidence("launch", {**course, "source_table": "Articles"}))
        self.assertIsNone(experience_evidence("beginner", {**course, "industries": ["Без опыта", "С опытом"]}))

    def test_industry_aliases_are_narrow_and_experience_is_not_industry(self):
        self.assertTrue(industry_matches("ритейл", {"industries": ["Розница"]}))
        self.assertTrue(industry_matches("e-commerce", {"industries": ["ECom"]}))
        self.assertTrue(industry_matches("HoReCa", {"industries": ["HoReСa"]}))
        self.assertFalse(industry_matches("Без опыта", {"industries": ["Без опыта"]}))
        self.assertFalse(industry_matches("неизвестная сфера", {"industries": ["Розница"]}))

    def test_goal_search_uncertainty_and_clarification_are_preserved(self):
        self.engine.metadata.update({
            "confidence": {"status": "uncertain", "reason": "unverified_constraint"},
            "clarification": {"question": "Уточните", "options": [{"token": "signed"}]},
            "query_rules": {"unsupported_constraints": ["price"]},
            "focus": {"kind": "text", "label": "начинающий"},
            "coverage": "unknown",
            "notice": "search notice",
        })
        p = {**self.base, "goal": "бесплатный курс"}
        result = recommend_for_profile(self.engine, p)
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["goal_search"]["confidence"]["reason"], "unverified_constraint")
        self.assertEqual(result["goal_search"]["clarification"]["options"][0]["token"], "signed")
        self.assertEqual(result["goal_search"]["query_rules"]["unsupported_constraints"], ["price"])
        self.assertEqual(result["goal_search"]["notice"], "search notice")
        self.assertEqual(result["goal_search"]["focus"]["label"], "начинающий")
        self.assertEqual(result["goal_search"]["coverage"], "unknown")
        p["events"] = [{"entity_key": "course:base", "action": "completed"}]
        plan = development_plan_for_profile(self.engine, p)
        self.assertEqual(plan["status"], "uncertain")
        self.assertIn(plan["plan_status"], {"ready", "partial"})
        self.assertEqual(plan["goal_search"]["confidence"]["reason"], "unverified_constraint")

    def test_clarification_is_forwarded_and_requires_same_goal(self):
        p = {**self.base, "goal": "команда", "clarification_token": "signed"}
        recommend_for_profile(self.engine, p)
        self.assertEqual(self.engine.last_options, {"clarification_token": "signed"})
        recommend_for_profile(self.engine, {**self.base, "goal": "команда", "clarification_text": "найм"})
        self.assertEqual(self.engine.last_options, {"clarification_text": "найм"})
        with self.assertRaises(ValueError):
            recommend_for_profile(self.engine, {**self.base, "clarification_token": "signed"})
        with self.assertRaises(ValueError):
            recommend_for_profile(self.engine, {**p, "clarification_text": "найм"})

    def test_constraints_remain_uncertain_even_if_search_confidence_conflicts(self):
        self.engine.metadata.update({
            "confidence": {"status": "unvalidated"},
            "query_rules": {"unsupported_constraints": ["price"]},
        })
        result = recommend_for_profile(self.engine, {**self.base, "goal": "бесплатный курс"})
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["goal_search"]["query_rules"]["unsupported_constraints"], ["price"])

    def test_history_signal_types_and_duplicate_strength(self):
        profile = {**self.base, "events": [
            {"entity_key": "course:base", "action": "started"},
            {"entity_key": "course:base", "action": "viewed"},
        ]}
        normalized = validate_profile(self.engine, profile)
        self.assertEqual(len(normalized["events"]), 1)
        self.assertEqual(normalized["events"][0]["action"], "started")
        plan = development_plan_for_profile(self.engine, profile)
        self.assertTrue(plan["steps"])
        self.assertEqual(plan["method"], "activity_profile_plan_v2")
        self.assertEqual(plan["steps"][0]["evidence"]["signal"], "started")
        self.assertIn("начали курс", plan["steps"][0]["why"])
        self.assertNotIn("завершённым", plan["steps"][0]["why"])

    def test_explicit_activity_strength_changes_only_grounded_candidates(self):
        self.engine.answer = [dict(self.engine.catalog[4]), dict(self.engine.catalog[1])]
        def related(*args, **kwargs):
            return [dict(self.engine.catalog[1])]
        with patch("alfa_reco.profile.recommend", side_effect=related):
            viewed = recommend_for_profile(self.engine, {
                **self.base, "goal": "команда",
                "events": [{"entity_key": "course:base", "action": "viewed"}],
            })
            completed = recommend_for_profile(self.engine, {
                **self.base, "goal": "команда",
                "events": [{"entity_key": "course:base", "action": "completed"}],
            })
        self.assertEqual(viewed["results"][0]["entity_key"], "article:tax")
        self.assertEqual(completed["results"][0]["entity_key"], "course:next")
        self.assertEqual(completed["results"][0]["profile_evidence"]["activity"]["action"], "completed")
        self.assertEqual({r["entity_key"] for r in viewed["results"]},
                         {r["entity_key"] for r in completed["results"]})

    def test_viewed_and_interested_are_not_course_completion(self):
        for action, phrase in (("viewed", "просмотр"), ("interested", "интерес")):
            with self.subTest(action=action):
                plan = development_plan_for_profile(self.engine, {
                    **self.base, "events": [{"entity_key": "course:base", "action": action}],
                })
                self.assertEqual(plan["method"], "activity_profile_plan_v2")
                self.assertEqual(plan["steps"][0]["evidence"]["signal"], action)
                self.assertIn(phrase, plan["steps"][0]["why"])
                self.assertNotIn("завершённым", plan["steps"][0]["why"])

    def test_completed_course_is_excluded_but_same_title_is_not_proof_of_duplicate(self):
        self.engine.catalog.append(material("course:copy", "Управление командой сотрудников"))
        self.engine.answer.extend([self.engine.catalog[0], self.engine.catalog[-1]])
        result = recommend_for_profile(self.engine, {
            **self.base, "goal": "команда",
            "events": [{"entity_key": "course:base", "action": "completed"}],
        })
        self.assertNotIn("course:base", [r["entity_key"] for r in result["results"]])
        self.assertIn("course:copy", [r["entity_key"] for r in result["results"]])

    def test_explicit_revisit_and_cross_kind_title_are_respected(self):
        self.engine.catalog.append(material("webinar:same", "Управление командой сотрудников", ["Управление командой"]))
        self.engine.answer.extend([self.engine.catalog[0], self.engine.catalog[-1]])
        p = {**self.base, "goal": "команда", "events": [{"entity_key": "course:base", "action": "completed"}]}
        result = recommend_for_profile(self.engine, p)
        keys = [r["entity_key"] for r in result["results"]]
        self.assertNotIn("course:base", keys)
        self.assertIn("webinar:same", keys)
        result = recommend_for_profile(self.engine, {**p, "allow_revisit": True})
        self.assertIn("course:base", [r["entity_key"] for r in result["results"]])

    def test_active_items_removed_from_alternatives(self):
        self.engine.metadata["alternatives"] = [self.engine.catalog[0]]
        result = recommend_for_profile(self.engine, {
            **self.base, "goal": "команда", "events": [{"entity_key": "course:base", "action": "started"}],
        })
        self.assertEqual(result["goal_search"]["alternatives"], [])

    def test_plan_does_not_assume_same_title_means_same_material(self):
        copy = material("webinar:copy", "Управление командой сотрудников", ["Управление командой"])
        self.engine.catalog.append(copy)
        plan = development_plan_for_profile(self.engine, {
            **self.base, "events": [{"entity_key": "course:base", "action": "completed"}],
        })
        self.assertIn("webinar:copy", [step["material"]["entity_key"] for step in plan["steps"]])

    def test_no_profile_and_empty_goal_results_do_not_invent_candidates(self):
        self.assertEqual(recommend_for_profile(self.engine, self.base)["results"], [])
        self.engine.answer = []
        result = recommend_for_profile(self.engine, {**self.base, "goal": "неизвестная тема"})
        self.assertEqual(result["results"], [])
        self.assertEqual(result["status"], "insufficient_evidence")

    def test_goal_restricts_plan_to_search_candidates(self):
        self.engine.answer = [dict(self.engine.catalog[-1])]
        plan = development_plan_for_profile(self.engine, {
            **self.base, "goal": "налоги", "events": [{"entity_key": "course:base", "action": "completed"}],
        })
        self.assertEqual(plan["steps"], [])
        self.assertEqual(plan["status"], "insufficient_evidence")

    def test_industry_unavailable_is_reported_and_not_guessed(self):
        result = recommend_for_profile(self.engine, {**self.base, "goal": "команда", "industry": "Авиакосмос"})
        self.assertEqual(result["profile_usage"]["industry"], "no_catalog_match")
        self.assertFalse(any(r["profile_evidence"]["industry"] for r in result["results"]))

    def test_preferences_are_soft_and_do_not_create_a_match_for_unknown_metadata(self):
        result = recommend_for_profile(self.engine, {
            **self.base, "goal": "команда", "industry": "Авиакосмос",
            "preferred_kinds": ["podcast"],
        })
        self.assertEqual(len(result["results"]), 3)
        self.assertEqual(result["profile_usage"]["industry"], "no_catalog_match")
        self.assertTrue(all(not r["profile_evidence"]["preferred_kind"] for r in result["results"]))

    def test_interest_or_format_alone_does_not_invent_goal(self):
        for extra in ({"industry": "Торговля"}, {"preferred_kinds": ["course"]}):
            with self.subTest(extra=extra):
                result = recommend_for_profile(self.engine, {**self.base, **extra})
                self.assertEqual(result["results"], [])
                self.assertEqual(result["status"], "insufficient_evidence")

    def test_goal_search_cannot_return_invalid_or_duplicate_items(self):
        self.engine.answer = [{"entity_key": "unknown"}]
        with self.assertRaisesRegex(ValueError, "unknown or duplicate"):
            recommend_for_profile(self.engine, {**self.base, "goal": "команда"})
        self.engine.answer = [self.engine.catalog[1], self.engine.catalog[1]]
        with self.assertRaisesRegex(ValueError, "unknown or duplicate"):
            development_plan_for_profile(self.engine, {**self.base, "goal": "команда"})

    def test_profile_validation_rejects_wrong_generation_events_and_values(self):
        cases = [
            {**self.base, "generation": "old"},
            {**self.base, "extra": "bad"},
            {**self.base, "business_stage": "made_up"},
            {**self.base, "experience": "made_up"},
            {**self.base, "preferred_kinds": ["glossary"]},
            {**self.base, "events": [{"entity_key": "article:tax", "action": "completed"}]},
            {**self.base, "events": [{"entity_key": "course:missing", "action": "viewed"}]},
            {**self.base, "events": [{"entity_key": "course:base", "action": "purchase"}]},
            {**self.base, "goal": " "},
            {**self.base, "allow_revisit": "yes"},
        ]
        for profile in cases:
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                recommend_for_profile(self.engine, profile)

    def test_legacy_history_plan_still_works_without_new_fields(self):
        from alfa_reco.development_plan import development_plan

        plan = development_plan(self.engine.catalog, [], [], ["course:base"])
        self.assertTrue(plan["steps"])
        self.assertNotIn("profile_matches", plan["steps"][0])


if __name__ == "__main__":
    unittest.main()
