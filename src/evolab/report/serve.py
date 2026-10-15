"""A dashboard kiszolgálása helyben (127.0.0.1), a Cloudflare-tunnel mögé.

Szándékosan csak egyetlen oldalt ad ki: `GET /` és `GET /index.html` -> `reports/index.html`.
Minden más útvonal 404 (a riport-JSON-ok, a data/, a kísérletnapló kívülről nem látszik).
Csak olvasás; a fájlt a napi futás `report` lépése frissíti.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ALLOWED = {"/", "/index.html"}


def make_handler(page: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "evolab-dashboard"
        sys_version = ""

        def _send(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path not in ALLOWED:
                return self._send(404, b"not found")
            if not page.exists():
                return self._send(503, "A dashboard még nem készült el (evolab report).".encode())
            return self._send(200, page.read_bytes(), "text/html; charset=utf-8")

        do_HEAD = do_GET

        def log_message(self, fmt, *args):  # csak a hibák kerüljenek a naplóba
            if args and str(args[1]).startswith(("4", "5")) and str(args[1]) != "404":
                super().log_message(fmt, *args)

    return Handler


def serve(page: Path, host: str = "127.0.0.1", port: int = 8790) -> None:
    ThreadingHTTPServer((host, port), make_handler(page)).serve_forever()
