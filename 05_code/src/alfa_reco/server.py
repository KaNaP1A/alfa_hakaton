"""Loopback-only development API. Deploy behind a production server for public use."""

import errno
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}


def make_server(engine, port=8000):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, format, *args):
            # Do not write user queries into access logs.
            return

        def send_json(self, status, payload):
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
            engine = self.server.engine
            if len(self.path) > 8192:
                self.send_json(414, {"error": "URL too long"})
                return
            host = self.headers.get("Host", "")
            if host not in {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }:
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
            if parsed.path not in {"/health", "/suggest", "/search"}:
                self.send_json(404, {"error": "Unknown endpoint"})
                return
            try:
                query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=10)
                if any(len(value) != 1 for value in query.values()):
                    raise ValueError("Duplicate parameters are not allowed")
                params = {key: value[0] for key, value in query.items()}
                allowed = (
                    {"q", "limit"}
                    if parsed.path == "/suggest"
                    else {
                        "q",
                        "top",
                        "mode",
                        "kind",
                        "selection_id",
                        "selection_generation",
                    }
                    if parsed.path == "/search"
                    else set()
                )
                if params.keys() - allowed:
                    raise ValueError("Unknown parameters")
                if parsed.path == "/health":
                    payload = {
                        "status": "ok",
                        "generation": engine.generation,
                        "hybrid_available": engine.encoder is not None,
                        "catboost_available": engine.encoder is not None
                        and (engine.path / "catboost_meta.json").exists()
                        and __import__("importlib").util.find_spec("catboost") is not None,
                        "catalog_count": len(engine.catalog),
                    }
                elif parsed.path == "/suggest":
                    payload = engine.suggest(params.get("q", ""), int(params.get("limit", 6)))
                else:
                    payload = engine.search(
                        params.get("q", ""),
                        mode=params.get("mode", "bm25"),
                        top=int(params.get("top", 5)),
                        kind=params.get("kind"),
                        selection_id=params.get("selection_id"),
                        selection_generation=params.get("selection_generation"),
                    )
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
                return
            except Exception as error:
                logging.getLogger(__name__).error("Search failed: %s", type(error).__name__)
                self.send_json(500, {"error": "Internal search error"})
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
    return server


def serve(args):
    from .search import SearchEngine

    # Reserve the port before loading a model; close it if initialization fails.
    with make_server(None, args.port) as server:
        server.engine = SearchEngine(args.output, semantic=args.hybrid)
        url = f"http://127.0.0.1:{server.server_port}"
        print(f"Local interface: {url}", flush=True)
        if args.open_browser:
            import webbrowser

            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
