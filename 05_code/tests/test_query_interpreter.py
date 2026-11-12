import json
import unittest

from alfa_reco.query_interpreter import OllamaInterpreter, grounded_match, grounded_span, route


def response(goal="", obj="", constraints=None):
    return {
        "message": {
            "content": json.dumps(
                {"goal": goal, "object": obj, "constraints": constraints or []}, ensure_ascii=False
            )
        }
    }


class InterpreterTests(unittest.TestCase):
    def test_routing(self):
        self.assertEqual(route("и на"), "skip_empty")
        self.assertEqual(route("кофейня"), "short")
        self.assertEqual(route("Как удержать сотрудников а не клиентов"), "complex")
        self.assertEqual(
            route("хочу начать продавать товары через маркетплейс прямо из дома"), "complex"
        )
        self.assertEqual(
            route("как составить трудовой договор для удалённого сотрудника"), "skip_simple"
        )

    def test_grounding_rejects_hallucinated_partial_word(self):
        self.assertIsNone(grounded_span("кофе", "кофейня"))
        self.assertIsNone(grounded_span("купить кофе", "кофейня"))
        self.assertEqual(grounded_span("кофейня", "Хочу открыть кофейню"), "кофейню")
        self.assertEqual(
            grounded_span("открыть кофейню", "Хочу открыть кофейню"), "открыть кофейню"
        )
        self.assertIsNone(grounded_span("123", "абв123г"))

    def test_invalid_generated_information_is_discarded(self):
        obj = OllamaInterpreter(
            transport=lambda _: response("заказать кофе", "кофе", ["Санкт-Петербург"])
        )
        value = obj.analyze("кофейня")
        self.assertEqual(value["status"], "ungrounded")
        self.assertEqual(value["discarded"], 3)
        self.assertEqual(value["object"], "")
        self.assertEqual(grounded_match(value, {"кофейн"}), 0)

    def test_preserve_negation_and_disable_boost(self):
        obj = OllamaInterpreter(transport=lambda _: response("удержать сотрудников", "сотрудников"))
        value = obj.analyze("как удержать сотрудников, а не клиентов")
        self.assertTrue(value["negation_present"])
        self.assertEqual(grounded_match(value, {"сотрудник"}), 0)
        self.assertEqual(value["object"], "сотрудников")

    def test_verified_fields_and_cache(self):
        calls = []
        obj = OllamaInterpreter(
            transport=lambda body: calls.append(body) or response("открыть кофейню", "кофейня")
        )
        value = obj.analyze("хочу открыть кофейню")
        self.assertEqual(value["status"], "ok")
        self.assertEqual(value["object"], "кофейню")
        self.assertEqual(grounded_match(value, {"кофейн"}), 1)
        self.assertTrue(obj.analyze("хочу открыть кофейню")["cached"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model"], "gemma3:1b")
        self.assertFalse(calls[0]["stream"])

    def test_object_is_not_repeated_as_a_constraint(self):
        obj = OllamaInterpreter(
            transport=lambda _: response("удержать сотрудников", "сотрудников", ["сотрудников"])
        )
        value = obj.analyze("как удержать сотрудников, а не клиентов")
        self.assertEqual(value["object"], "сотрудников")
        self.assertEqual(value["constraints"], [])

    def test_malformed_timeout_and_type_fallback(self):
        for output in [
            {"message": {"content": "not json"}},
            {"message": {"content": '{"goal": 3, "object": "x", "constraints": []}'}},
        ]:
            self.assertEqual(
                OllamaInterpreter(transport=lambda _, output=output: output).analyze("кофейня")[
                    "status"
                ],
                "unavailable",
            )

        def timeout(_):
            raise TimeoutError("offline")

        self.assertEqual(
            OllamaInterpreter(transport=timeout).analyze("кофейня")["status"], "unavailable"
        )

    def test_busy_degrades_without_blocking(self):
        obj = OllamaInterpreter(transport=lambda _: response())
        obj.slot.acquire()
        try:
            self.assertEqual(obj.analyze("кофейня")["status"], "busy")
        finally:
            obj.slot.release()
