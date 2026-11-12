import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from examples.backend_client import RecommendationClient


class BackendClientTests(unittest.TestCase):
    def test_search_passes_suggestion_and_keeps_original_query(self):
        with patch("examples.backend_client.urlopen", return_value=io.BytesIO(b'{"results": []}')) as call:
            result = RecommendationClient(timeout=8).search(
                "как открыть кафе", selection_id="topic:1", selection_generation="g1"
            )
        params = parse_qs(urlparse(call.call_args.args[0].full_url).query)
        self.assertEqual(params["q"], ["как открыть кафе"])
        self.assertEqual(params["mode"], ["relevance"])
        self.assertEqual(params["selection_id"], ["topic:1"])
        self.assertEqual(params["selection_generation"], ["g1"])
        self.assertEqual(call.call_args.kwargs["timeout"], 8)
        self.assertEqual(result, {"results": []})

    def test_recommend_posts_generation_and_viewed(self):
        with patch("examples.backend_client.urlopen", return_value=io.BytesIO(b'{"results": []}')) as call:
            RecommendationClient().recommend("g1", ["business"], ["course:1"])
        request = call.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {
            "generation": "g1", "categories": ["business"], "viewed": ["course:1"]
        })

    def test_http_error_is_explicit(self):
        error = HTTPError("http://localhost", 400, "Bad request", {}, io.BytesIO(b'{"error": "bad"}'))
        with patch("examples.backend_client.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "HTTP 400: bad"):
                RecommendationClient().search("")
