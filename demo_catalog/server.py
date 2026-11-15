"""Loopback-only catalog demonstrator; no purchases, authentication or real access claims."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}


def handler(catalog):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            allowed = {f"localhost:{self.server.server_port}", f"127.0.0.1:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed or (self.headers.get("Origin") and self.headers.get("Origin") != "http://" + self.headers.get("Host")):
                self.send_error(403)
                return
            path = urlsplit(self.path).path
            if path == "/api/catalog":
                data = json.dumps(catalog, ensure_ascii=False).encode()
                content_type = "application/json"
            elif path in ASSETS:
                filename, content_type = ASSETS[path]
                data = (ROOT / filename).read_bytes()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler(catalog)) as server:
        print(f"Локальный демонстрационный каталог: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
