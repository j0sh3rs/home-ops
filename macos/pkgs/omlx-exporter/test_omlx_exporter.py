import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import omlx_exporter as ex


class FlattenTest(unittest.TestCase):
    def test_nested_numbers_bools_and_lists(self):
        data = {"b": {"tokens": 5, "ok": True}, "a": [1.5, {"x": 2}], "name": "m", "none": None}
        self.assertEqual(
            list(ex.flatten(data)),
            [("a.0", 1.5), ("a.1.x", 2.0), ("b.ok", 1.0), ("b.tokens", 5.0)],
        )

    def test_non_finite_numbers_are_dropped(self):
        self.assertEqual(list(ex.flatten({"n": float("nan"), "i": float("inf"), "v": 1})), [("v", 1.0)])


class RenderTest(unittest.TestCase):
    def test_up_and_escaped_paths(self):
        text = ex.render(True, {"alltime": {'m"x': {"t": 3}}}, 0.25)
        self.assertIn("omlx_up 1\n", text)
        self.assertIn("omlx_scrape_duration_seconds 0.250000\n", text)
        self.assertIn('omlx_stat{scope="alltime",path="m\\"x.t"} 3.0\n', text)

    def test_down(self):
        self.assertIn("omlx_up 0\n", ex.render(False, {}, 0.0))


class CollectTest(unittest.TestCase):
    def test_all_scopes_ok(self):
        seen = []

        def fetch(base, key, scope):
            seen.append((base, key, scope))
            return {"requests": 2}

        text = ex.collect("http://h:1", "k", fetch)
        self.assertEqual(seen, [("http://h:1", "k", "session"), ("http://h:1", "k", "alltime")])
        self.assertIn("omlx_up 1\n", text)
        self.assertIn('omlx_stat{scope="session",path="requests"} 2.0\n', text)

    def test_one_scope_failing_marks_down_but_keeps_the_other(self):
        def fetch(base, key, scope):
            if scope == "session":
                raise OSError("boom")
            return {"requests": 9}

        text = ex.collect("http://h:1", "k", fetch)
        self.assertIn("omlx_up 0\n", text)
        self.assertIn('omlx_stat{scope="alltime",path="requests"} 9.0\n', text)
        self.assertNotIn('scope="session"', text)


class ServerTest(unittest.TestCase):
    def test_metrics_and_404(self):
        server = ex.make_server("127.0.0.1", 0, lambda: "omlx_up 1\n")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            port = server.server_address[1]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics") as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers["Content-Type"], "text/plain; version=0.0.4")
                self.assertEqual(resp.read(), b"omlx_up 1\n")
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/other")
            self.assertEqual(err.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()


class FetchSessionTest(unittest.TestCase):
    """The real fetch() against a stub of oMLX's cookie-session admin API."""

    COOKIE = "omlx_admin_session"

    def setUp(self):
        test = self
        self.sessions = set()
        self.logins = 0

        class Handler(BaseHTTPRequestHandler):
            def _json(self, code, body, headers=()):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for name, value in headers:
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                if self.path != "/admin/api/login" or body.get("api_key") != "sekret":
                    self._json(401, {"detail": "Invalid API key"})
                    return
                test.logins += 1
                token = f"tok{test.logins}"
                test.sessions.add(token)
                self._json(200, {"success": True}, [("Set-Cookie", f"{test.COOKIE}={token}; HttpOnly; Path=/; SameSite=lax")])

            def do_GET(self):
                if self.headers.get("Authorization"):
                    self._json(401, {"detail": "bearer not accepted"})
                    return
                cookie = self.headers.get("Cookie", "")
                token = cookie.partition("=")[2] if cookie.startswith(test.COOKIE + "=") else None
                if self.path.startswith("/admin/api/stats") and token in test.sessions:
                    self._json(200, {"requests": 4})
                else:
                    self._json(401, {"detail": "Admin authentication required"})

            def log_message(self, fmt, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        ex.reset_session()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_logs_in_reuses_session_and_recovers_after_invalidation(self):
        self.assertEqual(ex.fetch(self.base, "sekret", "session"), {"requests": 4})
        self.assertEqual(ex.fetch(self.base, "sekret", "alltime"), {"requests": 4})
        self.assertEqual(self.logins, 1)
        self.sessions.clear()  # server forgets the session (restart, expiry)
        self.assertEqual(ex.fetch(self.base, "sekret", "session"), {"requests": 4})
        self.assertEqual(self.logins, 2)

    def test_bad_key_raises_without_leaking_it(self):
        with self.assertRaises(Exception) as err:
            ex.fetch(self.base, "wrong-key", "session")
        self.assertNotIn("wrong-key", str(err.exception))


if __name__ == "__main__":
    unittest.main()
