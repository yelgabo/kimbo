"""Integration tests for the static-file allowlist and security headers.

Boots KimboHandler on an ephemeral loopback port and asserts that source /
config / dotfile paths are refused while the game's frontend assets serve.

Run from repo root: `python3 -m unittest tests.test_static_deny`
or single file: `python3 tests/test_static_deny.py`.
"""

import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server import KimboHandler, RateLimiter, db_init  # noqa: E402


class StaticDenyTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        db_path = os.path.join(cls._tmp.name, "test.db")
        db_init(db_path)
        KimboHandler.db_path = db_path
        KimboHandler.expected_origin = None
        KimboHandler.trust_proxy = False
        KimboHandler.limiter = RateLimiter()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), KimboHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)
        cls._tmp.cleanup()

    def _get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            resp = urllib.request.urlopen(url, timeout=5)
            return resp.status, dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers)

    def _raw_status(self, request_target):
        """Send a request with an exact request-target the URL parsers would
        otherwise rewrite (e.g. '//server.py', an embedded NUL). Return the
        integer status from the response line.
        """
        req = (
            f"GET {request_target} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.port}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("latin-1")
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as s:
            s.sendall(req)
            buf = b""
            while b"\r\n" not in buf:
                chunk = s.recv(1024)
                if not chunk:
                    break
                buf += chunk
        # e.g. b"HTTP/1.1 404 Not Found\r\n..."
        return int(buf.split(b" ", 2)[1])

    # ── denied ──

    def test_server_source_denied(self):
        status, _ = self._get("/server.py")
        self.assertEqual(status, 404)

    def test_tests_dir_denied(self):
        status, _ = self._get("/tests/test_validate.py")
        self.assertEqual(status, 404)

    def test_markdown_denied(self):
        status, _ = self._get("/CLAUDE.md")
        self.assertEqual(status, 404)

    def test_git_config_denied(self):
        status, _ = self._get("/.git/config")
        self.assertEqual(status, 404)

    def test_dotdir_settings_denied(self):
        status, _ = self._get("/.claude/settings.local.json")
        self.assertEqual(status, 404)

    def test_config_json_denied(self):
        status, _ = self._get("/railway.json")
        self.assertEqual(status, 404)

    def test_traversal_segment_denied(self):
        # A dotfile segment (including '..') is refused before any FS access.
        status, _ = self._get("/src/../server.py")
        self.assertEqual(status, 404)

    def test_double_slash_source_denied_by_logic(self):
        # '//server.py' resolves to <repo>/server.py; the allow-check runs on
        # that resolved path, so it's denied by logic (not by interpreter
        # normalization of the leading '//').
        self.assertEqual(self._raw_status("//server.py"), 404)

    def test_stray_docs_asset_denied(self):
        # A file with an allowlisted extension outside src/ (the untracked
        # docs/ dir) must NOT be served: scoping is by location, not just ext.
        self.assertEqual(self._get("/docs/architecture.svg")[0], 404)
        self.assertEqual(self._get("/docs/architecture.png")[0], 404)

    def test_null_byte_returns_404_not_500(self):
        # Passes the extension check under src/, then open() raises ValueError
        # (embedded NUL) — must be caught and turned into 404, not a 500.
        self.assertEqual(self._raw_status("/src/main.js%00.png"), 404)

    # ── allowed ──

    def test_index_served(self):
        status, headers = self._get("/")
        self.assertEqual(status, 200)
        # Security headers ride on static responses too.
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("Content-Security-Policy", headers)
        self.assertIn("Referrer-Policy", headers)

    def test_styles_served(self):
        status, _ = self._get("/styles.css")
        self.assertEqual(status, 200)

    def test_module_served(self):
        status, _ = self._get("/src/main.js")
        self.assertEqual(status, 200)

    # ── headers on API + errors ──

    def test_security_headers_on_api(self):
        status, headers = self._get("/api/leaderboard?limit=1")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("Content-Security-Policy", headers)

    def test_security_headers_on_404(self):
        _, headers = self._get("/server.py")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")


if __name__ == "__main__":
    unittest.main()
