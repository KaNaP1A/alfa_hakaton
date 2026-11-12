"""Loopback-only development API. Deploy behind a production server for public use."""

import errno
import json
import logging
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/lab": ("lab.html", "text/html; charset=utf-8"),
    "/lab.js": ("lab.js", "text/javascript; charset=utf-8"),
    "/lab.css": ("lab.css", "text/css; charset=utf-8"),
}


def make_server(engine, port=8000, default_mode=None):
    if default_mode not in {None, "bm25", "hybrid", "catboost", "ensemble", "relevance"}:
        raise ValueError("Invalid default search mode")

    class Handler(BaseHTTPRequestHandler):
        def local_request(self):
            allowed = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            return host in allowed and (not origin or origin in {f"http://{host}"})

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, format, *args):
            # Do not write user queries into access logs.
            return

        def send_json(self, status, payload):
            self.server.record_status(urlsplit(self.path).path, status)
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_body(status, body, "application/json; charset=utf-8")

        def send_body(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; "
                "style-src 'self'; img-src 'self'; connect-src 'self'; "
                "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            )
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # User cancelled an obsolete autocomplete request.

        def do_GET(self):
            started = time.perf_counter()
            try:
                self.handle_get()
            finally:
                self.server.record_latency(urlsplit(self.path).path, time.perf_counter() - started)

        def handle_get(self):
            engine = self.server.engine
            if len(self.path) > 8192:
                self.send_json(414, {"error": "URL too long"})
                return
            if not self.local_request():
                self.send_json(403, {"error": "Local Host header required"})
                return
            parsed = urlsplit(self.path)
            if parsed.path in ASSETS:
                filename, content_type = ASSETS[parsed.path]
                # Exact allowlist only: never expose database, arbitrary paths or directories.
                asset = Path(__file__).parent / "web" / filename
                try:
                    body = asset.read_bytes()
                except OSError:
                    self.send_json(500, {"error": "UI assets unavailable"})
                    return
                self.send_body(200, body, content_type)
                return
            if parsed.path not in {
                "/health",
                "/suggest",
                "/search",
                "/catalog",
                "/lab/data",
                "/lab/pool",
                "/lab/template",
            }:
                self.send_json(404, {"error": "Unknown endpoint"})
                return
            try:
                query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=10)
                if any(len(value) != 1 for value in query.values()):
                    raise ValueError("Duplicate parameters are not allowed")
                params = {key: value[0] for key, value in query.items()}
                allowed = (
                    {"q", "kind", "limit"}
                    if parsed.path == "/catalog"
                    else {"index"}
                    if parsed.path == "/lab/pool"
                    else (
                        {"q", "limit"}
                        if parsed.path == "/suggest"
                        else {
                            "q",
                            "top",
                            "mode",
                            "kind",
                            "selection_id",
                            "selection_generation",
                            "clarification_token",
                            "clarification_text",
                        }
                        if parsed.path == "/search"
                        else set()
                    )
                )
                if params.keys() - allowed:
                    raise ValueError("Unknown parameters")
                if parsed.path == "/catalog":
                    from .suggestions import validate_query

                    q = params.get("q", "")
                    validate_query(q)
                    kind = params.get("kind", "")
                    limit = int(params.get("limit", 30))
                    from .eligibility import USER_KINDS

                    if not 1 <= limit <= 50 or kind and kind not in USER_KINDS:
                        raise ValueError("Invalid catalog filter")
                    payload = {
                        "generation": engine.generation,
                        "items": [
                            {
                                k: item[k]
                                for k in ("entity_key", "title", "description", "kind", "topics")
                            }
                            for item in engine.catalog
                            if item["kind"] in USER_KINDS
                            and (not kind or item["kind"] == kind)
                            and q.casefold() in item["title"].casefold()
                        ][:limit],
                    }
                elif parsed.path in {"/lab/data", "/lab/pool", "/lab/template"}:
                    from .lab import lab_data

                    payload = lab_data(parsed.path, params)
                elif parsed.path == "/health":
                    payload = {
                        "status": "ok",
                        "generation": engine.generation,
                        "hybrid_available": engine.encoder is not None,
                        "default_search_mode": self.server.default_mode
                        or ("ensemble" if engine.encoder is not None else "bm25"),
                        "relevance_available": (
                            engine.path / "relevance" / "CURRENT.json"
                        ).exists(),
                        "catboost_available": engine.encoder is not None
                        and (engine.path / "catboost_small_meta.json").exists()
                        and __import__("importlib").util.find_spec("catboost") is not None,
                        "ensemble_available": engine.encoder is not None
                        and (engine.path / "ensemble_config.json").exists()
                        and (engine.path / "catboost_small_meta.json").exists()
                        and __import__("importlib").util.find_spec("catboost") is not None,
                        "catalog_count": len(engine.catalog),
                        "searchable_count": sum(
                            item["kind"] != "glossary" for item in engine.catalog
                        ),
                        "latency_ms": self.server.latency_summary(),
                        "http_errors": self.server.error_summary(),
                    }
                elif parsed.path == "/suggest":
                    payload = engine.suggest(params.get("q", ""), int(params.get("limit", 6)))
                else:
                    payload = engine.search(
                        params.get("q", ""),
                        mode=params.get(
                            "mode",
                            self.server.default_mode
                            or ("ensemble" if engine.encoder is not None else "bm25"),
                        ),
                        top=int(params.get("top", 5)),
                        kind=params.get("kind"),
                        selection_id=params.get("selection_id"),
                        selection_generation=params.get("selection_generation"),
                        clarification_token=params.get("clarification_token"),
                        clarification_text=params.get("clarification_text"),
                    )
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
                return
            except Exception as error:
                logging.getLogger(__name__).error("Search failed: %s", type(error).__name__)
                self.send_json(500, {"error": "Internal search error"})
                return
            self.send_json(200, payload)

        def do_POST(self):
            started = time.perf_counter()
            try:
                self.handle_post()
            finally:
                self.server.record_latency(urlsplit(self.path).path, time.perf_counter() - started)

        def handle_post(self):
            if not self.local_request():
                self.send_json(403, {"error": "Local Host and Origin required"})
                return
            if self.path != "/recommend":
                self.send_json(404, {"error": "Unknown endpoint"})
                return
            try:
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("JSON required")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError("Invalid body size")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or set(data) != {
                    "generation",
                    "categories",
                    "viewed",
                }:
                    raise ValueError("Invalid profile fields")
                engine = self.server.engine
                if data["generation"] != engine.generation:
                    raise ValueError("Catalog changed; refresh local profile")
                from .personalization import recommend

                payload = {
                    "generation": engine.generation,
                    "results": recommend(
                        engine.catalog,
                        data["categories"],
                        data["viewed"],
                        vectors=engine._relevance.vectors["card"]
                        if engine._relevance is not None
                        else None,
                    ),
                }
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self.send_json(400, {"error": str(error)})
                return
            self.send_json(200, payload)

    if not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            raise ValueError(
                f"Порт {port} уже занят. Если поиск уже запущен, откройте "
                f"http://127.0.0.1:{port}. Для отдельного запуска укажите другой --port."
            ) from error
        raise
    server.engine = engine
    server.default_mode = default_mode
    server.latencies = defaultdict(lambda: deque(maxlen=1000))
    server.http_errors = defaultdict(lambda: {"4xx": 0, "5xx": 0})
    server.latency_lock = threading.Lock()

    def record_latency(path, seconds):
        if path in {"/search", "/suggest", "/recommend"}:
            with server.latency_lock:
                server.latencies[path].append(seconds * 1000)

    def latency_summary():
        with server.latency_lock:
            snapshot = {key: sorted(values) for key, values in server.latencies.items() if values}
        return {
            key: {
                "n": len(values),
                "p50": round(values[(len(values) - 1) // 2], 1),
                "p95": round(values[int((len(values) - 1) * 0.95)], 1),
            }
            for key, values in snapshot.items()
        }

    def record_status(path, status):
        if path in {"/search", "/suggest", "/recommend"} and 400 <= status <= 599:
            with server.latency_lock:
                server.http_errors[path]["4xx" if status < 500 else "5xx"] += 1

    def error_summary():
        with server.latency_lock:
            return {key: dict(value) for key, value in server.http_errors.items()}

    server.record_latency = record_latency
    server.latency_summary = latency_summary
    server.record_status = record_status
    server.error_summary = error_summary
    return server


def serve(args):
    from .search import SearchEngine

    # Reserve the port before loading a model; close it if initialization fails.
    relevance = getattr(args, "relevance", False)
    with make_server(None, args.port, default_mode="relevance" if relevance else None) as server:
        server.engine = SearchEngine(
            args.output,
            semantic=args.hybrid,
            llm_enabled=not relevance and not getattr(args, "no_llm", False),
        )
        if relevance:
            server.engine.relevance_backend()
        url = f"http://127.0.0.1:{server.server_port}"
        print(f"Local interface: {url}", flush=True)
        if args.open_browser:
            import webbrowser

            webbrowser.open(url + getattr(args, "start_page", "/"))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
