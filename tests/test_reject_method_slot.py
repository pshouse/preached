"""F-01: a 405 must release the in-flight slot it acquired.

POST, PUT, DELETE and PATCH used to call ``_reject_method``, which acquires
in ``_blocked`` and never reached ``_respond``'s finally. Four of those from
one client key filled the cap for the life of the process. Search and
``/healthz`` have separate tables; both leaked.

These tests talk raw sockets at a BM25-only server with a synthetic index
under a temp directory. Loopback is all of 127/8, so each source address is
its own client key.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import json
import os
import threading
import time
import unittest

from test_exposure import _Gate, _Releases, _Served, _connect, _get, _read_response, _wait

SOURCE = "127.0.0.5"
PROBE = "127.0.0.2"
OTHER = "127.0.0.6"

METHODS = ("GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE")
HANDLED = {"GET", "HEAD", "POST", "PUT", "DELETE", "PATCH"}
REJECTED = {"POST", "PUT", "DELETE", "PATCH"}
# Bare path, and the target a successful GET of that path uses.
PATHS = (
    "/",
    "/healthz",
    "/api/search",
    "/api/side",
    "/api/sermon/wesley-001",
    "/static/favicon.svg",
    "/no/such",
)
BRANCHES = ("handled", "disabled", "busy", "429", "bad_request", "exception")


def _exchange(port: int, method: str, target: str, *, source: str, host: str = "127.0.0.1"):
    sock = _connect(port, source)
    try:
        message = (
            f"{method} {target} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Connection: close\r\n"
            "\r\n"
        )
        sock.sendall(message.encode("latin-1"))
        return _read_response(sock)
    finally:
        sock.close()


class _Counts:
    """acquire_slot successes and release_slot calls. Equal means nothing leaked."""

    def __init__(self, server) -> None:
        self.acquired = 0
        self.released = 0
        self._lock = threading.Lock()
        real_acquire = server.acquire_slot
        real_release = server.release_slot

        def acquire(key, *, health=False):
            ok = real_acquire(key, health=health)
            if ok:
                with self._lock:
                    self.acquired += 1
            return ok

        def release(key, *, health=False):
            real_release(key, health=health)
            with self._lock:
                self.released += 1

        server.acquire_slot = acquire
        server.release_slot = release

    def balanced(self) -> bool:
        with self._lock:
            return self.released == self.acquired


class RejectMethodSlotTests(_Served):
    """Four (then eight) 405s from one key, then a GET is 200 and the table is empty.

    On origin/main the fourth 405 sticks the cap, the wait for release times
    out, and the GET is 503.
    """

    def _serve_one(self):
        return self._serve(max_connections=16, max_per_client=8, max_requests=4)

    def _posts(self, port, path: str, n: int) -> None:
        for _ in range(n):
            status, headers, body = _exchange(port, "POST", path, source=SOURCE)
            self.assertEqual(status, 405, body)
            self.assertEqual(json.loads(body), {"error": "method not allowed"})
            allow = headers.get("allow", "")
            self.assertIn("GET", allow)
            self.assertIn("HEAD", allow)

    def _after_posts(self, port, server, releases: _Releases, n_posts: int, *, search: bool) -> None:
        released = releases.wait_for(n_posts)
        if search:
            status, _, body = _get(
                port, "/api/search?q=grace&mode=bm25&k=1", source=SOURCE
            )
        else:
            status, _, body = _get(port, "/healthz", source=SOURCE)
        self.assertEqual(
            (released, status),
            (True, 200),
            "tables search=%s health=%s body=%r" % (server._slots_by_key, server._health_slots_by_key, body),
        )
        if search:
            self.assertEqual(json.loads(body)["mode"], "bm25")
        else:
            health = json.loads(body)
            self.assertTrue(health["ok"])
            self.assertEqual(health["slots_stuck"], 0)
            self.assertNotIn(SOURCE, body.decode())
        # The GET releases too. Both tables, and the cap clocks, are empty.
        self.assertTrue(releases.wait_for(n_posts + 1))
        self.assertEqual(releases.count, n_posts + 1)
        self.assertEqual(server._slots_by_key, {})
        self.assertEqual(server._health_slots_by_key, {})
        self.assertEqual(server._capped_since, {})
        self.assertEqual(server._health_capped_since, {})

    def test_four_then_eight_posts_to_search_then_get_is_200(self) -> None:
        port, _app, server = self._serve_one()
        releases = _Releases(server)
        path = "/api/search?q=grace&mode=bm25&k=1"
        self._posts(port, path, 4)
        self._after_posts(port, server, releases, 4, search=True)
        # The counter is cumulative: the GET above was release number 5.
        # Eight more 405s are releases 6..13, then the following GET is 14.
        # Re-base by checking the delta inside a fresh counter.
        releases2 = _Releases(server)
        self._posts(port, path, 8)
        self._after_posts(port, server, releases2, 8, search=True)

    def test_four_then_eight_posts_to_healthz_then_get_is_200(self) -> None:
        port, _app, server = self._serve_one()
        releases = _Releases(server)
        self._posts(port, "/healthz", 4)
        self._after_posts(port, server, releases, 4, search=False)
        releases2 = _Releases(server)
        self._posts(port, "/healthz", 8)
        self._after_posts(port, server, releases2, 8, search=False)

    def test_post_holds_the_slot_until_the_405_is_written(self) -> None:
        for path, health in (
            ("/api/search?q=grace&mode=bm25&k=1", False),
            ("/healthz", True),
        ):
            with self.subTest(path=path):
                port, _app, server = self._serve(max_connections=8, max_per_client=4, max_requests=1)
                gate = _Gate(self, server, "release_slot")
                table = server._health_slots_by_key if health else server._slots_by_key
                sock = _connect(port, SOURCE)
                self.addCleanup(sock.close)
                sock.sendall(
                    (
                        f"POST {path} HTTP/1.1\r\n"
                        "Host: 127.0.0.1\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    ).encode("latin-1")
                )
                status, headers, body = _read_response(sock)
                self.assertEqual(status, 405, body)
                self.assertEqual(json.loads(body), {"error": "method not allowed"})
                self.assertIn("GET", headers.get("allow", ""))
                # The body was readable before release_slot returned.
                self.assertTrue(gate.entered.wait(3))
                self.assertEqual(table, {SOURCE: 1})
                other = server._slots_by_key if health else server._health_slots_by_key
                self.assertEqual(other, {})
                gate.open.set()
                self.assertTrue(gate.done.wait(3))
                self.assertEqual(table, {})


class SlotClockTests(_Served):
    """The cap clock and the /healthz count. No key or address is in the body."""

    def test_reaching_the_cap_starts_the_clock_and_dropping_below_clears_it(self) -> None:
        _port, _app, server = self._serve(max_requests=2)
        self.assertTrue(server.acquire_slot("k"))
        self.assertNotIn("k", server._capped_since)
        self.assertTrue(server.acquire_slot("k"))
        self.assertIn("k", server._capped_since)
        self.assertFalse(server.acquire_slot("k"))
        started = server._capped_since["k"]
        server.release_slot("k")
        self.assertNotIn("k", server._capped_since)
        self.assertEqual(server._slots_by_key, {"k": 1})
        self.assertTrue(server.acquire_slot("k"))
        self.assertGreaterEqual(server._capped_since["k"], started)
        server.release_slot("k")
        server.release_slot("k")
        self.assertEqual(server._slots_by_key, {})
        self.assertEqual(server._capped_since, {})

    def test_health_cap_is_a_separate_clock(self) -> None:
        _port, _app, server = self._serve(max_requests=1)
        self.assertTrue(server.acquire_slot("k", health=True))
        self.assertIn("k", server._health_capped_since)
        self.assertNotIn("k", server._capped_since)
        self.assertEqual(server._slots_by_key, {})
        server.release_slot("k", health=True)
        self.assertEqual(server._health_slots_by_key, {})
        self.assertEqual(server._health_capped_since, {})

    def test_more_than_n_seconds_counts_and_exactly_n_does_not(self) -> None:
        _port, _app, server = self._serve(max_requests=4)
        server.slot_cap_stuck_s = 30
        started = 1_000.0
        with server._conn_lock:
            server._slots_by_key["search-key"] = 4
            server._capped_since["search-key"] = started
            server._health_slots_by_key["health-key"] = 4
            server._health_capped_since["health-key"] = started
        self.assertEqual(server.slots_stuck_at_cap(now=started + 30), 0)
        self.assertEqual(server.slots_stuck_at_cap(now=started + 30.0001), 2)
        with server._conn_lock:
            server._slots_by_key["search-key"] = 3
        self.assertEqual(server.slots_stuck_at_cap(now=started + 31), 1)

    def test_slot_cap_stuck_s_reads_the_env_and_rejects_a_bad_value(self) -> None:
        previous = os.environ.get("PREACHED_SLOT_CAP_STUCK_S")
        try:
            os.environ["PREACHED_SLOT_CAP_STUCK_S"] = "12.5"
            _port, _app, server = self._serve()
            self.assertEqual(server.slot_cap_stuck_s, 12.5)
            for raw in ("0", "-3", "nope", ""):
                os.environ["PREACHED_SLOT_CAP_STUCK_S"] = raw
                _port, _app, server = self._serve()
                self.assertEqual(server.slot_cap_stuck_s, 30.0, raw)
        finally:
            if previous is None:
                os.environ.pop("PREACHED_SLOT_CAP_STUCK_S", None)
            else:
                os.environ["PREACHED_SLOT_CAP_STUCK_S"] = previous

    def test_healthz_shows_a_count_when_a_key_sits_at_the_cap(self) -> None:
        port, app, server = self._serve(max_connections=16, max_per_client=4, max_requests=4)
        server.slot_cap_stuck_s = 30
        status, _, body = _get(port, "/healthz", source=PROBE)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["slots_stuck"], 0)

        release, entered = self._block_search(app)
        held = []
        for _ in range(4):
            sock = _connect(port, SOURCE)
            self.addCleanup(sock.close)
            sock.sendall(
                b"GET /api/search?q=hold&mode=bm25&k=1 HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Connection: close\r\n"
                b"\r\n"
            )
            held.append(sock)
        for _ in held:
            self.assertTrue(entered.acquire(timeout=3))
        self.assertEqual(server._slots_by_key.get(SOURCE), 4)
        quiet = _get(port, "/healthz", source=PROBE)[2]
        self.assertEqual(json.loads(quiet)["slots_stuck"], 0)

        with server._conn_lock:
            server._capped_since[SOURCE] = time.monotonic() - 31
        body = _get(port, "/healthz", source=PROBE)[2]
        health = json.loads(body)
        self.assertEqual(health["slots_stuck"], 1)
        self.assertNotIn(SOURCE, body.decode())
        self.assertNotIn("search-key", body.decode())

        health_release, health_entered = _block_health(self, app, 4)
        health_held = []
        for _ in range(4):
            sock = _connect(port, OTHER)
            self.addCleanup(sock.close)
            sock.sendall(
                b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
            )
            health_held.append(sock)
        for _ in health_held:
            self.assertTrue(health_entered.acquire(timeout=3))
        self.assertEqual(server._health_slots_by_key.get(OTHER), 4)
        with server._conn_lock:
            server._health_capped_since[OTHER] = time.monotonic() - 31
        body = _get(port, "/healthz", source=PROBE)[2]
        self.assertEqual(json.loads(body)["slots_stuck"], 2)
        decoded = body.decode()
        self.assertNotIn(SOURCE, decoded)
        self.assertNotIn(OTHER, decoded)
        self.assertNotIn(PROBE, decoded)

        release.set()
        health_release.set()
        for sock in held:
            self.assertEqual(_read_response(sock)[0], 200)
        for sock in health_held:
            self.assertEqual(_read_response(sock)[0], 200)
        self.assertTrue(
            _wait(lambda: server._slots_by_key == {} and server._health_slots_by_key == {})
        )
        self.assertEqual(server._capped_since, {})
        self.assertEqual(server._health_capped_since, {})
        done = _get(port, "/healthz", source=PROBE)[2]
        self.assertEqual(json.loads(done)["slots_stuck"], 0)

    def test_disabled_healthz_body_has_no_slots_stuck_field(self) -> None:
        port, app, _server = self._serve()
        real = app.disabled
        app.disabled = lambda: True
        self.addCleanup(setattr, app, "disabled", real)
        status, _, body = _get(port, "/healthz", source=SOURCE)
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body), {"ok": False, "disabled": True})


def _block_health(test: unittest.TestCase, app, n_block: int):
    """Hold the first ``n_block`` ``app.health`` calls. Later calls run."""
    release = threading.Event()
    entered = threading.Semaphore(0)
    real = app.health
    lock = threading.Lock()
    left = [n_block]

    def health():
        with lock:
            block = left[0] > 0
            if block:
                left[0] -= 1
        if block:
            entered.release()
            release.wait(5)
        return real()

    app.health = health
    test.addCleanup(release.set)
    test.addCleanup(setattr, app, "health", real)
    return release, entered


class SlotReleaseMatrixTests(_Served):
    """Every method, every path, every refusal: both slot tables end empty.

    ``handled`` is in the matrix so a 405 that is allowed past ``_blocked``
    is checked, not only the branches that return before the slot is taken.
    """

    def test_every_method_path_and_branch_releases_both_tables(self) -> None:
        port, app, server = self._serve(
            max_connections=64,
            max_per_client=32,
            max_requests=4,
            rate_limit=10**9,
            global_rate_limit=10**9,
            health_rate_limit=10**9,
            health_global_rate_limit=10**9,
        )
        counts = _Counts(server)
        limits = (
            app.rate_limiter,
            app.global_limiter,
            app.health_limiter,
            app.health_global_limiter,
        )
        saved_limits = [limiter.limit for limiter in limits]
        real_disabled = app.disabled
        real_headers = server.RequestHandlerClass._security_headers

        def boom(self) -> None:
            raise RuntimeError("slot-probe")

        try:
            for branch in BRANCHES:
                self._arm(app, server, branch, limits, real_disabled, real_headers, boom)
                try:
                    for method in METHODS:
                        for path in PATHS:
                            with self.subTest(branch=branch, method=method, path=path):
                                before = counts.acquired
                                status, headers, body = _exchange(
                                    port,
                                    method,
                                    _target(method, path, branch),
                                    source=SOURCE,
                                    host=_host(method, path, branch),
                                )
                                self.assertTrue(
                                    _wait(
                                        lambda: counts.balanced()
                                        and server._conn_total == 0
                                        and server._slots_by_key == {}
                                        and server._health_slots_by_key == {}
                                    )
                                )
                                self.assertEqual(server._slots_by_key, {})
                                self.assertEqual(server._health_slots_by_key, {})
                                self.assertEqual(server._capped_since, {})
                                self.assertEqual(server._health_capped_since, {})
                                expected = _expected(method, path, branch)
                                self.assertIn(status, expected, body)
                                if branch == "handled" and method in HANDLED:
                                    # A handled request got past _blocked and took a slot.
                                    self.assertEqual(counts.acquired, before + 1)
                                if status == 405:
                                    self.assertEqual(json.loads(body), {"error": "method not allowed"})
                                    self.assertIn("GET", headers.get("allow", ""))
                                    self.assertIn("HEAD", headers.get("allow", ""))
                                self._assert_branch_body(branch, method, path, status, headers, body)
                finally:
                    self._disarm(app, server, limits, saved_limits, real_disabled, real_headers)
        finally:
            self._disarm(app, server, limits, saved_limits, real_disabled, real_headers)

    def _arm(self, app, server, branch, limits, real_disabled, real_headers, boom) -> None:
        self._disarm(app, server, limits, [10**9, 10**9, 10**9, 10**9], real_disabled, real_headers)
        server.max_requests_per_client = 4
        if branch == "disabled":
            app.disabled = lambda: True
        elif branch == "busy":
            server.max_requests_per_client = 0
        elif branch == "429":
            for limiter in limits:
                limiter.limit = 0
        elif branch == "exception":
            server.RequestHandlerClass._security_headers = boom

    def _disarm(self, app, server, limits, saved_limits, real_disabled, real_headers) -> None:
        app.disabled = real_disabled
        server.max_requests_per_client = 4
        for limiter, limit in zip(limits, saved_limits):
            limiter.limit = limit
        server.RequestHandlerClass._security_headers = real_headers

    def _assert_branch_body(self, branch, method, path, status, headers, body) -> None:
        if method not in HANDLED or branch == "exception" or branch == "handled":
            return
        # HEAD advertises Content-Length and writes no bytes. The slot tables
        # are the assertion; the body checks below are for methods that send one.
        if method == "HEAD":
            self.assertEqual(body, b"")
            return
        payload = json.loads(body)
        if branch == "disabled":
            if path == "/healthz":
                self.assertEqual(payload, {"ok": False, "disabled": True})
            else:
                self.assertEqual(payload, {"error": "unavailable"})
        elif branch == "busy":
            self.assertEqual(payload, {"error": "unavailable"})
            self.assertEqual(headers.get("retry-after"), "1")
            self.assertEqual(headers.get("connection"), "close")
        elif branch == "429":
            self.assertEqual(payload, {"error": "too many requests"})
            self.assertIn("retry-after", headers)
        elif branch == "bad_request":
            if method in ("GET", "HEAD") and path in ("/api/search", "/api/side"):
                self.assertEqual(payload, {"error": "q is required"})
            else:
                self.assertEqual(payload, {"error": "host not allowed"})


def _target(method: str, path: str, branch: str) -> str:
    if branch == "bad_request" and method in ("GET", "HEAD") and path in ("/api/search", "/api/side"):
        return path
    if path == "/api/search":
        return "/api/search?q=grace&mode=bm25&k=1"
    if path == "/api/side":
        return "/api/side?q=grace&mode=bm25&k=1"
    return path


def _host(method: str, path: str, branch: str) -> str:
    if branch == "bad_request" and not (
        method in ("GET", "HEAD") and path in ("/api/search", "/api/side")
    ):
        return "evil.example"
    return "127.0.0.1"


def _expected(method: str, path: str, branch: str) -> set:
    if branch == "exception":
        # Headers stay buffered until end_headers. _security_headers raises
        # first, so the socket closes with no status line. A route that had
        # already flushed would still show that status.
        if method not in HANDLED:
            return {None}
        return {None, 500, 200, 405, 404}
    if method not in HANDLED:
        return {501}
    if branch == "disabled" or branch == "busy":
        return {503}
    if branch == "429":
        return {429}
    if branch == "bad_request":
        if method in ("GET", "HEAD") and path in ("/api/search", "/api/side"):
            return {400}
        return {421}
    if method in REJECTED:
        return {405}
    if path == "/no/such":
        return {404}
    return {200}


if __name__ == "__main__":
    unittest.main()
