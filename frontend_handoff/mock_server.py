#!/usr/bin/env python3
"""Local synthetic frontend fixture server; this is not the recommendation engine."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
GENERATION = "mock-generation-1"
ITEMS = [
    {"entity_key": "course:mock-team", "kind": "course", "title": "Основы управления командой",
     "description": "Вымышленный учебный курс для проверки интерфейса.", "topics": ["Команда"],
     "tags": [], "access_type": None, "canonical_url": None, "data_quality_flags": [],
     "promotion": {"text": "Познакомьтесь с основами управления командой: посмотрите программу курса.",
                   "source": "title_template", "source_fields": ["title"]},
     "price": {"status": "unknown", "source": None, "snapshot_only": True, "access_verified": False}},
    {"entity_key": "article:mock-feedback", "kind": "article", "title": "Обратная связь в команде",
     "description": "Вымышленная статья для проверки интерфейса.", "topics": ["Команда"],
     "tags": [], "access_type": None, "canonical_url": None, "data_quality_flags": [],
     "promotion": {"text": "Разберитесь с обратной связью в команде.",
                   "source": "title_template", "source_fields": ["title"]},
     "price": {"status": "unknown", "source": None, "snapshot_only": True, "access_verified": False}},
]


def result(item):
    return {**item, "reason": "Пример связи с выбранной темой.", "method": "lexical_facets"}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path in ("/", "/app.js"):
            name = "index.html" if parsed.path == "/" else "app.js"
            content = (ROOT / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8" if name.endswith("html")
                             else "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        params = parse_qs(parsed.query)
        query = params.get("q", [""])[0]
        if parsed.path == "/health":
            self.send_json(200, {"status": "ok", "generation": GENERATION,
                                 "default_search_mode": "relevance", "relevance_available": False,
                                 "catalog_count": len(ITEMS), "searchable_count": len(ITEMS)})
        elif parsed.path == "/suggest":
            suggestions = [] if not query.strip() else [{
                "id": "mock-team", "label": "Управление командой", "kind": "topic",
                "support_count": 2, "evidence_entity_keys": [i["entity_key"] for i in ITEMS],
                "selection": {"id": "mock-team", "generation": GENERATION},
            }]
            self.send_json(200, {"query": query, "generation": GENERATION,
                                 "completions": suggestions, "related_topics": [],
                                 "status": "matched" if suggestions else "insufficient_input",
                                 "typo_tolerant_match": False})
        elif parsed.path == "/search":
            if not query.strip() or len(query) > 300 or params.get("mode", ["relevance"])[0] != "relevance":
                self.send_json(400, {"error": "Invalid mock query or mode"})
                return
            kind = params.get("kind", [""])[0]
            if kind and kind not in {"article", "course", "document", "podcast", "webinar", "calculator"}:
                self.send_json(400, {"error": "Invalid kind"})
                return
            empty = "пусто" in query.casefold() or "уточнение" in query.casefold()
            clarified = bool(params.get("clarification_text") or params.get("clarification_token"))
            found = [] if empty and not clarified else [i for i in ITEMS if not kind or i["kind"] == kind]
            self.send_json(200, {"query": query, "generation": GENERATION,
                                 "mode": "relevance_experimental", "results": found,
                                 "alternatives": [],
                                 "confidence": {"status": "unvalidated" if found else "empty"},
                                 "clarification": None if found else {
                                     "question": "Не удалось подобрать материал. Уточните задачу.",
                                     "options": [], "allow_text": True},
                                 "query_rules": {"unsupported_constraints": []}})
        elif parsed.path == "/catalog":
            kind = params.get("kind", [""])[0]
            self.send_json(200, {"generation": GENERATION, "items": [
                i for i in ITEMS if (not kind or i["kind"] == kind)
                and query.casefold() in i["title"].casefold()]})
        else:
            self.send_json(404, {"error": "Unknown mock endpoint"})

    def do_POST(self):
        if self.path not in ("/recommend", "/development-plan"):
            self.send_json(404, {"error": "Unknown mock endpoint"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384 or self.headers.get_content_type() != "application/json":
                raise ValueError("JSON required")
            data = json.loads(self.rfile.read(length))
            expected = {"generation", "categories", "viewed"}
            if self.path == "/development-plan":
                expected.add("completed")
            if not isinstance(data, dict) or set(data) != expected or data["generation"] != GENERATION:
                raise ValueError("Invalid mock profile or generation")
            if any(not isinstance(data[k], list) for k in expected - {"generation"}):
                raise ValueError("Profile fields must be lists")
            seen = data["viewed"] + data.get("completed", [])
            if any(not isinstance(key, str) or key not in {i["entity_key"] for i in ITEMS} for key in seen):
                raise ValueError("Unknown mock item")
            if any(key != "course:mock-team" for key in data.get("completed", [])):
                raise ValueError("Only a course can be completed")
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_json(400, {"error": "Invalid mock request"})
            return
        available = [result(i) for i in ITEMS if i["entity_key"] not in seen]
        if self.path == "/recommend":
            self.send_json(200, {"generation": GENERATION, "results": available})
            return
        steps = []
        if seen and available:
            steps.append({"number": 1, "title": "Продолжить тему", "material": available[0],
                          "why": "Пример тематической связи с историей.",
                          "action": "Посмотрите описание материала.",
                          "order_reason": "Условный следующий шаг.",
                          "evidence": {"entity_key": seen[0], "title": "Вымышленный материал",
                                       "signal": "completed" if seen[0] in data["completed"] else "viewed",
                                       "shared_topics_or_tags": ["Команда"]}})
        status = "partial" if steps else "insufficient_evidence" if seen else "needs_activity"
        self.send_json(200, {"generation": GENERATION, "method": "activity_content_plan_v1",
                             "status": status, "notice": "Учебный маршрут условный.", "steps": steps})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Synthetic mock: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
