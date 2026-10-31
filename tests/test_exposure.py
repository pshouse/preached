"""Exposure hardening: trusted-proxy keying, slot fairness, the /healthz bucket.

Every server test talks raw sockets. Loopback is all of 127/8 on Linux, so a
test can be several clients by binding 127.0.0.2, 127.0.0.3, and so on.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from app.server import (  # noqa: E402
    STATIC_DIR,
    App,
    client_key,
    make_server,
    parse_trusted_proxies,
)
from preached.search import Searcher  # noqa: E402
from preached.store import connect  # noqa: E402


def _nets(*entries: str) -> tuple:
    return tuple(ipaddress.ip_network(entry) for entry in entries)


def _connect(port: int, source: str = "127.0.0.1") -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", port), timeout=3, source_address=(source, 0))
    sock.settimeout(3)
    return sock


def _send(sock: socket.socket, path: str, headers: dict | None = None, close: bool = False) -> None:
    lines = [f"GET {path} HTTP/1.1", "Host: 127.0.0.1"]
    for name, value in (headers or {}).items():
        lines.append(f"{name}: {value}")
    if close:
        lines.append("Connection: close")
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))


def _read_response(sock: socket.socket) -> tuple[int | None, dict, bytes]:
    """One response. Status None means EOF before a status line."""
    data = b""
    while b"\r\n\r\n" not in data:
        try:
            chunk = sock.recv(4096)
        except (ConnectionResetError, TimeoutError):
            chunk = b""
        if not chunk:
            return None, {}, data
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    while len(rest) < length:
        chunk = sock.recv(4096)
        if not chunk:
            break
        rest += chunk
    return status, headers, rest[:length]


def _get(port: int, path: str, *, source: str = "127.0.0.1", headers: dict | None = None):
    sock = _connect(port, source)
    try:
        _send(sock, path, headers, close=True)
        return _read_response(sock)
    finally:
        sock.close()


def _is_closed(sock: socket.socket, within: float) -> bool:
    """True when the server closed the socket within ``within`` seconds."""
    sock.settimeout(within)
    try:
        return sock.recv(1) == b""
    except (TimeoutError, socket.timeout):
        return False
    except OSError:
        return True


def _wait(predicate, timeout: float = 2.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _read_final(sock: socket.socket) -> int | None:
    """The final status, after any interim 1xx. None means EOF or a reset first.

    A 100 Continue and the final response can arrive in one read, so this
    keeps its own buffer rather than calling ``_read_response`` twice.
    """
    data = b""
    while True:
        head, sep, rest = data.partition(b"\r\n\r\n")
        if sep:
            status = int(head.split(b"\r\n", 1)[0].split()[1])
            if status >= 200:
                return status
            data = rest
            continue
        try:
            chunk = sock.recv(4096)
        except (ConnectionResetError, TimeoutError):
            chunk = b""
        if not chunk:
            return None
        data += chunk


def _hold_after_finish(test: unittest.TestCase, server, seconds: float) -> None:
    """Hold each handler after ``finish`` and before its socket is closed."""
    handler = server.RequestHandlerClass
    real_finish = handler.finish

    def slow_finish(self) -> None:
        real_finish(self)
        time.sleep(seconds)

    handler.finish = slow_finish
    test.addCleanup(setattr, handler, "finish", real_finish)


class _Gate:
    """Holds the first call to ``server.<name>`` until ``open`` is set.

    ``entered`` is set when that call arrives, ``done`` once it has run.
    Later calls pass straight through.
    """

    def __init__(self, test: unittest.TestCase, server, name: str) -> None:
        self.entered = threading.Event()
        self.open = threading.Event()
        self.done = threading.Event()
        real = getattr(server, name)
        lock = threading.Lock()
        first = [True]

        def gated(*args, **kwargs):
            with lock:
                hold, first[0] = first[0], False
            if not hold:
                return real(*args, **kwargs)
            self.entered.set()
            self.open.wait(5)
            try:
                return real(*args, **kwargs)
            finally:
                self.done.set()

        setattr(server, name, gated)
        test.addCleanup(self.open.set)


class _Releases:
    """Counts ``release_slot`` calls so a test can wait for one, not sleep."""

    def __init__(self, server) -> None:
        self.count = 0
        self._cond = threading.Condition()
        real = server.release_slot

        def counted(*args, **kwargs):
            real(*args, **kwargs)
            with self._cond:
                self.count += 1
                self._cond.notify_all()

        server.release_slot = counted

    def wait_for(self, n: int, timeout: float = 3.0) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: self.count >= n, timeout)


class _Served(unittest.TestCase):
    def _serve(
        self,
        *,
        max_connections=None,
        max_per_client=None,
        max_requests=None,
        header_deadline_s=None,
        scarce_idle_s=None,
        **kwargs,
    ):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "wesley.sqlite"
        connection = connect(path)
        connection.execute(
            """
            INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text, sermon_number, word_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("wesley-001-c0000", "wesley-001", "Salvation by Faith", "zealboundary grace", 1, 2),
        )
        connection.commit()
        connection.close()
        connection = sqlite3.connect(path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        kwargs.setdefault("trusted_proxies", ())
        app = App(
            connection=connection,
            searcher=Searcher(connection),
            encode=None,
            fallback_note=None,
            model_name=None,
            hosts={"127.0.0.1", "localhost"},
            static_dir=STATIC_DIR,
            **kwargs,
        )
        server = make_server(app, "127.0.0.1", 0)
        # Joined by server_close, so no handler still uses the index when the
        # connection below is closed.
        server.daemon_threads = False
        server.block_on_close = True
        if max_connections is not None:
            server.max_connections = max_connections
        if max_per_client is not None:
            server.max_connections_per_client = max_per_client
        if max_requests is not None:
            server.max_requests_per_client = max_requests
        if header_deadline_s is not None:
            server.header_deadline_s = header_deadline_s
        if scarce_idle_s is not None:
            server.scarce_idle_s = scarce_idle_s
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # Cleanups run last-in first-out: stop the server, join its handler
        # threads, then close the index.
        self.addCleanup(connection.close)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1], app, server

    def _block_search(self, app: App):
        """Make /api/search?q=hold wait until the returned event is set."""
        release = threading.Event()
        entered = threading.Semaphore(0)
        real = app.search

        def search(query, *args, **kwargs):
            if query == "hold":
                entered.release()
                release.wait(5)
            return real(query, *args, **kwargs)

        app.search = search
        self.addCleanup(release.set)
        return release, entered


# Item 1: trusted-proxy X-Forwarded-For keying and the global backstop.


class ClientKeyTests(unittest.TestCase):
    def test_untrusted_peer_ignores_forwarded_for(self) -> None:
        self.assertEqual(client_key("192.0.2.9", ["203.0.113.5"], ()), "192.0.2.9")
        trusted = _nets("10.0.0.1/32")
        self.assertEqual(client_key("192.0.2.9", ["203.0.113.5"], trusted), "192.0.2.9")

    def test_right_most_untrusted_hop(self) -> None:
        trusted = _nets("10.0.0.0/24")
        # The client wrote 6.6.6.6; the proxy appended the real peer.
        self.assertEqual(client_key("10.0.0.1", ["6.6.6.6, 198.51.100.7"], trusted), "198.51.100.7")
        # Two trusted hops are skipped.
        self.assertEqual(
            client_key("10.0.0.1", ["6.6.6.6, 198.51.100.7, 10.0.0.2"], trusted), "198.51.100.7"
        )
        # Repeated headers are one list, in order.
        self.assertEqual(client_key("10.0.0.1", ["6.6.6.6", "198.51.100.7"], trusted), "198.51.100.7")

    def test_no_header_or_only_trusted_hops(self) -> None:
        trusted = _nets("10.0.0.0/24")
        self.assertEqual(client_key("10.0.0.1", None, trusted), "10.0.0.1")
        self.assertEqual(client_key("10.0.0.1", [], trusted), "10.0.0.1")
        self.assertEqual(client_key("10.0.0.1", ["10.0.0.3, 10.0.0.2"], trusted), "10.0.0.3")

    def test_garbage_hop_keys_on_the_nearest_trusted_address(self) -> None:
        trusted = _nets("10.0.0.0/24")
        for value in ("unknown", "198.51.100.7:443", "", "1.2.3.4, ", "_hidden"):
            with self.subTest(value=value):
                self.assertEqual(client_key("10.0.0.1", [value], trusted), "10.0.0.1")
        self.assertEqual(client_key("10.0.0.1", ["198.51.100.7, junk, 10.0.0.2"], trusted), "10.0.0.2")

    def test_mapped_ipv6_and_ipv6(self) -> None:
        trusted = _nets("10.0.0.1/32", "2001:db8::/64")
        self.assertEqual(client_key("::ffff:10.0.0.1", ["198.51.100.7"], trusted), "198.51.100.7")
        # An IPv6 client is keyed by its /64 (M4).
        self.assertEqual(client_key("2001:db8::5", ["2001:db8:1::9"], trusted), "2001:db8:1::/64")
        self.assertEqual(client_key("::ffff:192.0.2.9", ["203.0.113.5"], trusted), "192.0.2.9")

    def test_a_sibling_in_the_proxys_64_is_not_trusted(self) -> None:
        # Trust is by the configured network, never widened to the /64 used for keys.
        trusted = _nets("2001:db8::1/128")
        # A sibling peer's X-Forwarded-For is ignored; it is keyed by its /64.
        self.assertEqual(client_key("2001:db8::2", ["198.51.100.7"], trusted), "2001:db8::/64")
        # A sibling hop behind the real proxy is the client, not a skipped proxy.
        self.assertEqual(client_key("2001:db8::1", ["198.51.100.7, 2001:db8::2"], trusted), "2001:db8::/64")
        # The proxy itself is still trusted.
        self.assertEqual(client_key("2001:db8::1", ["198.51.100.7"], trusted), "198.51.100.7")

    def test_trusted_list_parsing_fails_closed(self) -> None:
        self.assertEqual(parse_trusted_proxies(None), ())
        self.assertEqual(parse_trusted_proxies(""), ())
        self.assertEqual(
            parse_trusted_proxies("127.0.0.1, 10.0.0.0/8 2001:db8::/32"),
            _nets("127.0.0.1/32", "10.0.0.0/8", "2001:db8::/32"),
        )
        for bad in ("10.0.0.1/8", "localhost", "10.0.0.256", "*"):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                parse_trusted_proxies(bad)

    def test_app_reads_the_env_and_defaults_to_none(self) -> None:
        from unittest import mock

        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("PREACHED_TRUSTED_PROXIES", None)
            app = App(None, None, None, None, None, {"x"}, STATIC_DIR)
            self.assertEqual(app.trusted_proxies, ())
            env["PREACHED_TRUSTED_PROXIES"] = "127.0.0.9"
            app = App(None, None, None, None, None, {"x"}, STATIC_DIR)
            self.assertEqual(app.trusted_proxies, _nets("127.0.0.9/32"))
            env["PREACHED_TRUSTED_PROXIES"] = "127.0.0.9/8"
            with self.assertRaises(SystemExit):
                App(None, None, None, None, None, {"x"}, STATIC_DIR)


class ForwardedForTests(_Served):
    def test_spoofed_forwarded_for_from_an_untrusted_peer_is_ignored(self) -> None:
        # Only 127.0.0.9 is a proxy. 127.0.0.2 rotates a fake XFF per request.
        port, _app, _server = self._serve(rate_limit=2, trusted_proxies=_nets("127.0.0.9/32"))
        statuses = [
            _get(port, "/api/search?q=grace", source="127.0.0.2", headers={"X-Forwarded-For": f"203.0.113.{n}"})[0]
            for n in range(1, 5)
        ]
        self.assertEqual(statuses, [200, 200, 429, 429])
        # The header named an address that never connected: it has its own budget
        # only if it were keyed, and it is not.
        self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.3")[0], 200)

    def test_spoofed_forwarded_for_with_no_trusted_proxies(self) -> None:
        port, _app, _server = self._serve(rate_limit=1)
        self.assertEqual(_get(port, "/api/search?q=grace", headers={"X-Forwarded-For": "127.0.0.1"})[0], 200)
        status, headers, body = _get(port, "/api/search?q=grace", headers={"X-Forwarded-For": "198.51.100.1"})
        self.assertEqual(status, 429)
        self.assertEqual(json.loads(body), {"error": "too many requests"})
        self.assertEqual(headers["retry-after"], "60")

    def test_trusted_proxy_keys_on_the_right_most_untrusted_hop(self) -> None:
        port, _app, _server = self._serve(rate_limit=1, trusted_proxies=_nets("127.0.0.9/32"))

        def via_proxy(xff):
            return _get(port, "/api/search?q=grace", source="127.0.0.9", headers={"X-Forwarded-For": xff})[0]

        self.assertEqual(via_proxy("198.51.100.7"), 200)
        self.assertEqual(via_proxy("198.51.100.7"), 429)
        # A different client behind the same proxy has its own bucket.
        self.assertEqual(via_proxy("198.51.100.8"), 200)
        # The client prepends a fresh address; the proxy appended the real one.
        self.assertEqual(via_proxy("192.0.2.77, 198.51.100.7"), 429)
        # A chain of trusted proxies is skipped.
        self.assertEqual(via_proxy("192.0.2.78, 198.51.100.7, 127.0.0.9"), 429)

    def test_global_backstop_caps_many_clients(self) -> None:
        port, _app, _server = self._serve(rate_limit=100, global_rate_limit=3)
        statuses = [_get(port, "/api/search?q=grace", source=f"127.0.0.{n}")[0] for n in range(2, 7)]
        self.assertEqual(statuses, [200, 200, 200, 429, 429])
        status, _, body = _get(port, "/api/search?q=grace", source="127.0.0.20")
        self.assertEqual(status, 429)
        self.assertEqual(json.loads(body), {"error": "too many requests"})

    def test_a_client_over_its_own_cap_does_not_spend_the_backstop(self) -> None:
        port, _app, _server = self._serve(rate_limit=1, global_rate_limit=3)
        hammer = [_get(port, "/api/search?q=grace", source="127.0.0.2")[0] for _ in range(6)]
        self.assertEqual(hammer, [200] + [429] * 5)
        others = [_get(port, "/api/search?q=grace", source=f"127.0.0.{n}")[0] for n in (3, 4)]
        self.assertEqual(others, [200, 200])

    def test_backstop_counts_proxied_clients(self) -> None:
        port, _app, _server = self._serve(
            rate_limit=100, global_rate_limit=2, trusted_proxies=_nets("127.0.0.9/32")
        )
        statuses = [
            _get(port, "/api/search?q=grace", source="127.0.0.9", headers={"X-Forwarded-For": f"198.51.100.{n}"})[0]
            for n in range(1, 4)
        ]
        self.assertEqual(statuses, [200, 200, 429])


# Item 2: per-client slot fairness.


class SlotFairnessTests(_Served):
    def _hold_idle(self, port: int, source: str, count: int, server) -> list[socket.socket]:
        """``count`` keep-alive connections from ``source``, each idle after one request."""
        held = []
        for _ in range(count):
            sock = _connect(port, source)
            _send(sock, "/healthz")
            status, headers, _ = _read_response(sock)
            self.assertEqual(status, 200)
            self.assertNotEqual(headers.get("connection"), "close")
            held.append(sock)
            self.addCleanup(sock.close)
        return held

    def test_few_clients_cannot_starve_a_new_one(self) -> None:
        # The PR #18 shape scaled down: 4 peers x 2 keep-alive connections fill 8.
        port, _app, server = self._serve(
            max_connections=8, max_per_client=2, header_deadline_s=10, scarce_idle_s=10
        )
        held = []
        for n in range(2, 6):
            held += self._hold_idle(port, f"127.0.0.{n}", 2, server)
        self.assertTrue(_wait(lambda: server._conn_total == 8))
        for n in range(6, 10):
            with self.subTest(newcomer=n):
                # A search, so the reserved /healthz connection cannot stand in.
                status, _, body = _get(port, "/api/search?q=grace", source=f"127.0.0.{n}")
                self.assertEqual(status, 200)
                self.assertIn("results", json.loads(body))
        closed = [sock for sock in held if _is_closed(sock, 0.5)]
        self.assertGreaterEqual(len(closed), 1)
        # A hog peer keeps at least one connection: only idle surplus goes.
        self.assertLessEqual(len(closed), 4)

    def test_one_client_cannot_take_more_than_its_share(self) -> None:
        port, _app, server = self._serve(max_connections=8, max_per_client=2, header_deadline_s=10)
        self._hold_idle(port, "127.0.0.2", 2, server)
        sock = _connect(port, "127.0.0.2")
        _send(sock, "/healthz", close=True)
        status, headers, _ = _read_response(sock)
        sock.close()
        self.assertEqual(status, 503)
        self.assertEqual(headers["connection"], "close")
        self.assertEqual(_get(port, "/healthz", source="127.0.0.3")[0], 200)

    def test_slow_header_senders_are_closed_for_a_newcomer(self) -> None:
        port, _app, server = self._serve(
            max_connections=4, max_per_client=2, header_deadline_s=10, scarce_idle_s=10
        )
        drips = []
        for n in (2, 3):
            for _ in range(2):
                sock = _connect(port, f"127.0.0.{n}")
                sock.sendall(b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\n")
                drips.append(sock)
                self.addCleanup(sock.close)
        self.assertTrue(_wait(lambda: server._conn_total == 4))
        self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.4")[0], 200)
        self.assertTrue(any(_is_closed(sock, 0.5) for sock in drips))

    def test_requests_in_flight_are_never_closed(self) -> None:
        port, app, server = self._serve(max_connections=4, max_per_client=2, header_deadline_s=10)
        release, entered = self._block_search(app)
        busy = []
        for n in (2, 3):
            for _ in range(2):
                sock = _connect(port, f"127.0.0.{n}")
                _send(sock, "/api/search?q=hold")
                busy.append(sock)
                self.addCleanup(sock.close)
        for _ in busy:
            self.assertTrue(entered.acquire(timeout=3))
        # Nothing can be closed: a search is refused, /healthz gets the reserve.
        self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.4")[0], 503)
        # The reserve is freed once that 503 is flushed, before the close.
        self.assertTrue(_wait(lambda: server._reserved_total == 0))
        status, headers, _ = _get(port, "/healthz", source="127.0.0.4")
        self.assertEqual(status, 200)
        self.assertEqual(headers["connection"], "close")
        release.set()
        for sock in busy:
            self.assertEqual(_read_response(sock)[0], 200)

    def test_slot_is_free_once_a_closing_response_is_read(self) -> None:
        port, _app, server = self._serve(max_connections=4, max_per_client=1)
        # Hold each handler after its response is flushed and before the
        # socket is closed: the window a fast client reconnects in.
        _hold_after_finish(self, server, 1.0)
        for path, expected in (("/healthz", 200), ("/api/search?q=grace", 200), ("/nope", 404)):
            with self.subTest(path=path):
                # The last subtest's reconnect may still be between its flush
                # and its release.
                self.assertTrue(_wait(lambda: server._conn_total == 0 and server._conn_by_ip == {}))
                sock = _connect(port, "127.0.0.2")
                self.addCleanup(sock.close)
                _send(sock, path, close=True)
                self.assertEqual(_read_response(sock)[0], expected)
                # The slot goes once the body is flushed, before the close.
                self.assertTrue(_wait(lambda: server._conn_total == 0 and server._conn_by_ip == {}, 0.5))
                self.assertFalse(_is_closed(sock, 0.05))
                # The same peer, at its cap of 1, gets straight back in.
                self.assertEqual(_get(port, "/healthz", source="127.0.0.2")[0], 200)

    def test_no_churn_between_equal_clients(self) -> None:
        # Every peer holds one: a newcomer is refused, not swapped in.
        port, _app, server = self._serve(max_connections=4, max_per_client=2, header_deadline_s=10, scarce_idle_s=10)
        held = []
        for n in range(2, 6):
            held += self._hold_idle(port, f"127.0.0.{n}", 1, server)
        self.assertTrue(_wait(lambda: server._conn_total == 4))
        self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.6")[0], 503)
        self.assertFalse(any(_is_closed(sock, 0.2) for sock in held))

    def test_keep_alive_idle_is_bounded_when_scarce(self) -> None:
        # 8 slots, scarce from 6 used (2 or fewer free).
        port, _app, server = self._serve(
            max_connections=8, max_per_client=8, header_deadline_s=10, scarce_idle_s=0.3
        )
        early = self._hold_idle(port, "127.0.0.2", 4, server)
        # Not scarce yet: these keep the long deadline.
        late = self._hold_idle(port, "127.0.0.3", 2, server)
        self.assertTrue(_wait(lambda: server._conn_total == 6))
        # The connections that went idle while scarce close within the short bound.
        started = time.monotonic()
        self.assertTrue(_is_closed(late[1], 2.0))
        self.assertLess(time.monotonic() - started, 1.5)
        # One that went idle before is still open.
        self.assertFalse(_is_closed(early[0], 0.5))

    def test_not_scarce_keeps_the_full_deadline(self) -> None:
        port, _app, server = self._serve(
            max_connections=32, max_per_client=4, header_deadline_s=10, scarce_idle_s=0.2
        )
        held = self._hold_idle(port, "127.0.0.2", 2, server)
        self.assertFalse(_is_closed(held[1], 0.8))

    def test_trusted_proxy_connections_and_per_client_request_slots(self) -> None:
        port, app, server = self._serve(
            max_connections=16,
            max_per_client=2,
            max_requests=1,
            header_deadline_s=10,
            trusted_proxies=_nets("127.0.0.9/32"),
        )
        release, entered = self._block_search(app)
        releases = _Releases(server)
        # The proxy is not held to the per-peer connection cap.
        first = _connect(port, "127.0.0.9")
        self.addCleanup(first.close)
        _send(first, "/api/search?q=hold", {"X-Forwarded-For": "198.51.100.7"})
        self.assertTrue(entered.acquire(timeout=3))
        # Same client, second slot: refused and closed.
        status, headers, body = _get(
            port, "/api/search?q=grace", source="127.0.0.9", headers={"X-Forwarded-For": "198.51.100.7"}
        )
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body), {"error": "unavailable"})
        self.assertEqual(headers["retry-after"], "1")
        self.assertEqual(headers["connection"], "close")
        # A spoofed left-hand hop does not escape the cap.
        status, _, _ = _get(
            port,
            "/api/search?q=grace",
            source="127.0.0.9",
            headers={"X-Forwarded-For": "192.0.2.1, 198.51.100.7"},
        )
        self.assertEqual(status, 503)
        # Three more open proxy connections at once, over the per-peer cap of 2.
        # They share the proxy's own key and its one /healthz request slot,
        # which is held until each response is written. Wait for each
        # release before the next request, or it is a correct busy 503
        # (RequestSlotRaceTests).
        for n in range(1, 4):
            self._hold_idle(port, "127.0.0.9", 1, server)
            self.assertTrue(releases.wait_for(n))
        self.assertTrue(_wait(lambda: server._conn_by_ip.get("127.0.0.9") == 4))
        # Another client through the same proxy, on several more connections.
        others = [
            _get(port, "/healthz", source="127.0.0.9", headers={"X-Forwarded-For": f"198.51.100.{n}"})[0]
            for n in range(20, 24)
        ]
        self.assertEqual(others, [200] * 4)
        release.set()
        self.assertEqual(_read_response(first)[0], 200)
        # 3 + 4 /healthz and the held search.
        self.assertTrue(releases.wait_for(8))
        self.assertEqual(server._slots_by_key, {})
        self.assertEqual(server._health_slots_by_key, {})

    def test_direct_peer_request_slots(self) -> None:
        port, app, server = self._serve(max_connections=16, max_per_client=4, max_requests=2, header_deadline_s=10)
        release, entered = self._block_search(app)
        socks = []
        for _ in range(2):
            sock = _connect(port, "127.0.0.2")
            _send(sock, "/api/search?q=hold")
            socks.append(sock)
            self.addCleanup(sock.close)
        for _ in socks:
            self.assertTrue(entered.acquire(timeout=3))
        self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.2")[0], 503)
        self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.3")[0], 200)
        release.set()
        for sock in socks:
            self.assertEqual(_read_response(sock)[0], 200)


# Item 3: /healthz in its own bucket.


class HealthBucketTests(_Served):
    def test_search_flood_does_not_starve_healthz(self) -> None:
        port, _app, _server = self._serve(rate_limit=2, global_rate_limit=3)
        statuses = [_get(port, "/api/search?q=grace", source=f"127.0.0.{n % 3 + 2}")[0] for n in range(6)]
        self.assertEqual(statuses.count(429), 3)
        # Per-client and global search budgets are both spent.
        self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.2")[0], 429)
        status, _, body = _get(port, "/healthz", source="127.0.0.2")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_healthz_flood_does_not_spend_the_search_budget(self) -> None:
        port, _app, _server = self._serve(rate_limit=1, global_rate_limit=1, health_rate_limit=3)
        health = [_get(port, "/healthz", source="127.0.0.2")[0] for _ in range(5)]
        self.assertEqual(health, [200, 200, 200, 429, 429])
        self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.2")[0], 200)

    def test_healthz_has_a_global_backstop_of_its_own(self) -> None:
        port, _app, _server = self._serve(health_rate_limit=10, health_global_rate_limit=2, global_rate_limit=5)
        health = [_get(port, "/healthz", source=f"127.0.0.{n}")[0] for n in range(2, 6)]
        self.assertEqual(health, [200, 200, 429, 429])
        self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.7")[0], 200)

    def test_healthz_bucket_follows_the_trusted_proxy_key(self) -> None:
        port, _app, _server = self._serve(health_rate_limit=1, trusted_proxies=_nets("127.0.0.9/32"))

        def via(xff):
            return _get(port, "/healthz", source="127.0.0.9", headers={"X-Forwarded-For": xff})[0]

        self.assertEqual(via("198.51.100.1"), 200)
        self.assertEqual(via("198.51.100.1"), 429)
        self.assertEqual(via("198.51.100.2"), 200)
        # From an untrusted peer the header is ignored.
        self.assertEqual(_get(port, "/healthz", source="127.0.0.2", headers={"X-Forwarded-For": "198.51.100.3"})[0], 200)
        self.assertEqual(_get(port, "/healthz", source="127.0.0.2", headers={"X-Forwarded-For": "198.51.100.4"})[0], 429)


# Round 1 of the PR #29 review.


class _FakeRequest:
    """Stands in for an accepted socket in the server's bookkeeping."""

    def __init__(self) -> None:
        self.shut = False

    def shutdown(self, how) -> None:
        self.shut = True


class EvictionOrderTests(_Served):
    """M1: a connection still receiving its headers is not taken for a newcomer."""

    def _hold_idle(self, port: int, source: str, count: int) -> list[socket.socket]:
        held = []
        for _ in range(count):
            sock = _connect(port, source)
            _send(sock, "/healthz")
            self.assertEqual(_read_response(sock)[0], 200)
            held.append(sock)
            self.addCleanup(sock.close)
            # Distinct idle times, so "oldest" is well defined.
            time.sleep(0.02)
        return held

    def test_half_sent_request_gets_a_response(self) -> None:
        # The CTO's pD.py: 4 slots, 127.0.0.5 holds 3, 127.0.0.6 holds 1.
        port, _app, server = self._serve(max_connections=4, header_deadline_s=10, scarce_idle_s=10)
        five = self._hold_idle(port, "127.0.0.5", 3)
        six = self._hold_idle(port, "127.0.0.6", 1)
        self.assertTrue(_wait(lambda: server._conn_total == 4))
        # 127.0.0.5 starts a request on its oldest connection and stops mid-headers.
        five[0].sendall(b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\n")
        self.assertTrue(_wait(lambda: any(c.reading for c in server._conns.values())))
        status, _, _ = _get(port, "/api/search?q=grace", source="127.0.0.9")
        self.assertEqual(status, 200)
        # The half-sent request completes and is answered.
        five[0].sendall(b"\r\n")
        self.assertEqual(_read_response(five[0])[0], 200)
        # Its oldest idle connection was the one closed.
        self.assertTrue(_is_closed(five[1], 1.0))
        _send(five[2], "/healthz")
        self.assertEqual(_read_response(five[2])[0], 200)
        _send(six[0], "/healthz")
        self.assertEqual(_read_response(six[0])[0], 200)

    def test_the_oldest_idle_connection_is_the_one_closed(self) -> None:
        port, _app, server = self._serve(max_connections=4, header_deadline_s=10, scarce_idle_s=10)
        two = self._hold_idle(port, "127.0.0.2", 3)
        self._hold_idle(port, "127.0.0.3", 1)
        self.assertTrue(_wait(lambda: server._conn_total == 4))
        self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.9")[0], 200)
        self.assertTrue(_is_closed(two[0], 1.0))
        for sock in two[1:]:
            _send(sock, "/healthz")
            self.assertEqual(_read_response(sock)[0], 200)

    def _bookkeeping(self, max_connections: int):
        _port, _app, server = self._serve(max_connections=max_connections, max_per_client=8)
        server.health_reserved = 0
        return server

    def test_mark_busy_is_false_after_a_hand_over(self) -> None:
        server = self._bookkeeping(2)
        a, b, c = _FakeRequest(), _FakeRequest(), _FakeRequest()
        self.assertTrue(server._acquire_connection(a, "127.0.0.2"))
        time.sleep(0.01)
        self.assertTrue(server._acquire_connection(b, "127.0.0.2"))
        self.assertTrue(server._acquire_connection(c, "127.0.0.3"))
        self.assertTrue(a.shut)
        self.assertFalse(b.shut)
        # The victim's handler finishes its headers too late: it must stop.
        self.assertFalse(server.mark_busy(a))
        self.assertTrue(server.mark_busy(b))

    def test_reading_is_taken_only_when_no_idle_one_is_left(self) -> None:
        server = self._bookkeeping(3)
        a, b, c = _FakeRequest(), _FakeRequest(), _FakeRequest()
        for request in (a, b, c):
            self.assertTrue(server._acquire_connection(request, "127.0.0.2"))
            time.sleep(0.01)
        # a and b are receiving headers (a started first); c is idle and newest.
        server.mark_reading(a)
        time.sleep(0.01)
        server.mark_reading(b)
        first = _FakeRequest()
        self.assertTrue(server._acquire_connection(first, "127.0.0.3"))
        self.assertEqual([a.shut, b.shut, c.shut], [False, False, True])
        # No idle one left: the longest-reading connection goes.
        second = _FakeRequest()
        self.assertTrue(server._acquire_connection(second, "127.0.0.4"))
        self.assertEqual([a.shut, b.shut], [True, False])
        # mark_idle clears reading.
        server.mark_idle(b)
        self.assertFalse(server._conns[b].reading)

    def test_a_reserved_healthz_connection_is_never_taken(self) -> None:
        server = self._bookkeeping(1)
        server.health_reserved = 2
        a, b, c, d = (_FakeRequest() for _ in range(4))
        self.assertTrue(server._acquire_connection(a, "127.0.0.2"))
        self.assertTrue(server.mark_busy(a))
        # Nothing to take: b is admitted on the reserve and stays idle.
        self.assertTrue(server._acquire_connection(b, "127.0.0.2"))
        self.assertTrue(server._conns[b].reserved)
        # 127.0.0.2 holds two more than a newcomer, but one is busy and one reserved.
        self.assertIsNone(server._pick_victim(0))
        self.assertTrue(server._acquire_connection(c, "127.0.0.3"))
        self.assertTrue(server._conns[c].reserved)
        self.assertFalse(server._acquire_connection(d, "127.0.0.4"))
        self.assertEqual([a.shut, b.shut, c.shut], [False, False, False])


class AuditLogTests(_Served):
    """M2: the log names the client key, and every refusal class is logged."""

    def test_proxied_request_logs_the_forwarded_key(self) -> None:
        port, _app, _server = self._serve(trusted_proxies=_nets("127.0.0.9/32"))
        with self.assertLogs(level="INFO") as logs:
            status, _, _ = _get(port, "/healthz?x=1", source="127.0.0.9", headers={"X-Forwarded-For": "198.51.100.7"})
            self.assertEqual(status, 200)
            self.assertTrue(_wait(lambda: any("GET /healthz" in line for line in logs.output)))
        line = next(line for line in logs.output if "GET /healthz" in line)
        self.assertTrue(line.endswith("127.0.0.9 198.51.100.7 GET /healthz 200"), line)

    def test_direct_request_logs_peer_twice_and_ipv6_keys_by_64(self) -> None:
        port, app, _server = self._serve()
        with self.assertLogs(level="INFO") as logs:
            _get(port, "/healthz", source="127.0.0.4")
            self.assertTrue(_wait(lambda: any("GET /healthz" in line for line in logs.output)))
        self.assertTrue(any(line.endswith("127.0.0.4 127.0.0.4 GET /healthz 200") for line in logs.output))
        self.assertEqual(app.client_key("2001:db8::1", None), "2001:db8::/64")

    def test_each_429_class_is_logged(self) -> None:
        port, _app, _server = self._serve(
            rate_limit=1, global_rate_limit=2, health_rate_limit=1, health_global_rate_limit=2
        )
        with self.assertLogs(level="WARNING") as logs:
            statuses = [
                _get(port, "/api/search?q=grace", source="127.0.0.2")[0],
                _get(port, "/api/search?q=grace", source="127.0.0.2")[0],  # client
                _get(port, "/api/search?q=grace", source="127.0.0.3")[0],
                _get(port, "/api/search?q=grace", source="127.0.0.4")[0],  # global
                _get(port, "/healthz", source="127.0.0.2")[0],
                _get(port, "/healthz", source="127.0.0.2")[0],  # health
                _get(port, "/healthz", source="127.0.0.3")[0],
                _get(port, "/healthz", source="127.0.0.4")[0],  # health-global
            ]
        self.assertEqual(statuses, [200, 429, 200, 429] * 2)
        text = "\n".join(logs.output)
        self.assertIn("refused 429-client 127.0.0.2 127.0.0.2 /api/search suppressed=0", text)
        self.assertIn("refused 429-global 127.0.0.4 127.0.0.4 /api/search suppressed=0", text)
        self.assertIn("refused 429-health 127.0.0.2 127.0.0.2 /healthz suppressed=0", text)
        self.assertIn("refused 429-health-global 127.0.0.4 127.0.0.4 /healthz suppressed=0", text)

    def test_over_cap_and_eviction_are_logged(self) -> None:
        port, _app, server = self._serve(max_connections=3, max_per_client=2, header_deadline_s=10, scarce_idle_s=10)
        server.health_reserved = 0
        held = []
        for _ in range(2):
            sock = _connect(port, "127.0.0.2")
            _send(sock, "/healthz")
            self.assertEqual(_read_response(sock)[0], 200)
            held.append(sock)
            self.addCleanup(sock.close)
        with self.assertLogs(level="WARNING") as logs:
            # Per-peer cap: 127.0.0.2 already holds 2.
            self.assertEqual(_get(port, "/healthz", source="127.0.0.2")[0], 503)
            third = _connect(port, "127.0.0.3")
            self.addCleanup(third.close)
            _send(third, "/healthz")
            self.assertEqual(_read_response(third)[0], 200)
            # Full: 127.0.0.4 takes one of 127.0.0.2's idle connections.
            self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.4")[0], 200)
        text = "\n".join(logs.output)
        self.assertIn("refused over-cap peer=127.0.0.2 suppressed=0", text)
        self.assertIn("refused evict 127.0.0.2->127.0.0.4 suppressed=0", text)

    def test_refusal_lines_are_rate_limited_with_a_count(self) -> None:
        from app.server import RefusalLog

        log = RefusalLog(interval_s=1.0)
        with self.assertLogs(level="WARNING") as logs:
            self.assertTrue(log.note("429-client", "a", now=10.0))
            self.assertFalse(log.note("429-client", "b", now=10.2))
            self.assertFalse(log.note("429-client", "c", now=10.9))
            # Another class has its own interval.
            self.assertTrue(log.note("over-cap", "d", now=10.5))
            self.assertTrue(log.note("429-client", "e", now=11.0))
        self.assertEqual(
            [line.split(":", 2)[2] for line in logs.output],
            [
                "refused 429-client a suppressed=0",
                "refused over-cap d suppressed=0",
                "refused 429-client e suppressed=2",
            ],
        )

    def test_suppressed_counts_are_flushed_at_shutdown(self) -> None:
        _port, _app, server = self._serve()
        server.refusals.note("429-client", "a", now=10.0)
        server.refusals.note("429-client", "b", now=10.2)
        server.refusals.note("429-client", "c", now=10.3)
        server.refusals.note("over-cap", "d", now=10.0)
        with self.assertLogs(level="WARNING") as logs:
            server.shutdown()
            server.server_close()
        self.assertEqual(
            [line.split(":", 2)[2] for line in logs.output],
            ["refused 429-client flush suppressed=2"],
        )
        # Flushed once: nothing is left to repeat.
        with self.assertNoLogs(level="WARNING"):
            server.refusals.flush()

    def test_suppressed_counts_are_flushed_when_a_handler_is_stuck(self) -> None:
        # Exit 1 path: drain gives up on a handler. The counts must be logged
        # before exit, without waiting for that handler (a SIGKILL follows).
        from unittest import mock

        import app.server as app_server

        port, app, server = self._serve()
        release, entered = self._block_search(app)
        sock = _connect(port)
        self.addCleanup(sock.close)
        _send(sock, "/api/search?q=hold", close=True)
        self.assertTrue(entered.acquire(timeout=3))
        server.refusals.note("429-client", "a", now=10.0)
        for _ in range(13):
            server.refusals.note("429-client", "b", now=10.2)
            server.refusals.note("busy", "c", now=10.2)
        server.shutdown()  # the serve loop has stopped, as after SIGTERM
        server.drain = lambda: app_server.PreachedServer.drain(server, timeout_s=0.3)
        connection = mock.Mock()
        app.close_embedder = mock.Mock()
        with mock.patch.dict(app_server._STOP, {"requested": True, "server": None, "stopping": False}):
            with self.assertLogs(level="WARNING") as logs, self.assertRaises(SystemExit) as raised:
                app_server.serve_until_stopped(server, app, connection)
        self.assertEqual(raised.exception.code, 1)
        stuck = [thread for thread in vars(server)["_threads"] if thread.is_alive()]
        self.assertEqual(len(stuck), 1, "the handler must still be stuck when the counts are logged")
        lines = [line.split(":", 2)[2] for line in logs.output]
        self.assertIn("refused 429-client flush suppressed=13", lines)
        self.assertIn("refused busy flush suppressed=12", lines)
        # Neither the index nor the session is closed under the stuck handler.
        connection.close.assert_not_called()
        app.close_embedder.assert_not_called()
        release.set()


class Ipv6KeyTests(_Served):
    """M4: IPv6 clients are keyed by /64."""

    def test_client_key_uses_the_64(self) -> None:
        self.assertEqual(client_key("2001:db8:0:0:1::1", None, ()), "2001:db8::/64")
        self.assertEqual(client_key("2001:db8::ffff", None, ()), "2001:db8::/64")
        self.assertEqual(client_key("2001:db8:0:1::1", None, ()), "2001:db8:0:1::/64")
        # IPv4 and IPv4-mapped stay per address.
        self.assertEqual(client_key("192.0.2.1", None, ()), "192.0.2.1")
        self.assertEqual(client_key("::ffff:192.0.2.1", None, ()), "192.0.2.1")
        # Behind a trusted proxy, the forwarded IPv6 hop is keyed by its /64 too.
        trusted = _nets("127.0.0.1/32")
        self.assertEqual(client_key("127.0.0.1", ["2001:db8::7"], trusted), "2001:db8::/64")
        self.assertEqual(client_key("127.0.0.1", ["2001:db8::8"], trusted), "2001:db8::/64")

    def test_addresses_in_one_64_share_a_rate_bucket(self) -> None:
        app = App(None, None, None, None, None, {"x"}, STATIC_DIR, rate_limit=2, trusted_proxies=())
        keys = [app.client_key(peer, None) for peer in ("2001:db8::1", "2001:db8::2", "2001:db8::3")]
        results = [app.allow(key, health=False) for key in keys]
        self.assertEqual(results[:2], [None, None])
        self.assertIs(results[2], app.rate_limiter)
        self.assertIsNone(app.allow(app.client_key("2001:db8:0:1::1", None), health=False))

    def test_addresses_in_one_64_share_the_connection_cap(self) -> None:
        _port, _app, server = self._serve(max_connections=16, max_per_client=2)
        requests = [_FakeRequest() for _ in range(4)]
        self.assertTrue(server._acquire_connection(requests[0], "2001:db8::1"))
        self.assertTrue(server._acquire_connection(requests[1], "2001:db8::2"))
        self.assertFalse(server._acquire_connection(requests[2], "2001:db8::3"))
        self.assertTrue(server._acquire_connection(requests[3], "2001:db8:0:1::1"))
        self.assertEqual(server._conn_by_ip["2001:db8::/64"], 2)

    def test_tailscale_addresses_are_keyed_per_address(self) -> None:
        # Every tailnet node is in fd7a:115c:a1e0::/48, in one /64; one key each.
        self.assertEqual(client_key("fd7a:115c:a1e0:ab12::1", None, ()), "fd7a:115c:a1e0:ab12::1")
        self.assertEqual(client_key("fd7a:115c:a1e0:ab12::2", None, ()), "fd7a:115c:a1e0:ab12::2")
        trusted = _nets("127.0.0.1/32")
        self.assertEqual(
            client_key("127.0.0.1", ["fd7a:115c:a1e0:ab12::3"], trusted), "fd7a:115c:a1e0:ab12::3"
        )
        # Just outside the /48 is keyed by /64 again.
        self.assertEqual(client_key("fd7a:115c:a1e1::1", None, ()), "fd7a:115c:a1e1::/64")
        app = App(None, None, None, None, None, {"x"}, STATIC_DIR, rate_limit=1, trusted_proxies=())
        for peer in ("fd7a:115c:a1e0:ab12::1", "fd7a:115c:a1e0:ab12::2"):
            self.assertIsNone(app.allow(app.client_key(peer, None), health=False))

    def test_tailscale_nodes_do_not_share_the_connection_cap(self) -> None:
        _port, _app, server = self._serve(max_connections=16, max_per_client=1)
        requests = [_FakeRequest() for _ in range(3)]
        self.assertTrue(server._acquire_connection(requests[0], "fd7a:115c:a1e0:ab12::1"))
        self.assertTrue(server._acquire_connection(requests[1], "fd7a:115c:a1e0:ab12::2"))
        self.assertFalse(server._acquire_connection(requests[2], "fd7a:115c:a1e0:ab12::1"))


class RefundAndHealthSlotTests(_Served):
    """Should-fix 1-3: backstop refunds, the reserved /healthz connection, health slots."""

    def test_a_global_refusal_does_not_spend_the_client_bucket(self) -> None:
        from app.server import RateLimiter

        app = App(None, None, None, None, None, {"x"}, STATIC_DIR, rate_limit=2, global_rate_limit=1, trusted_proxies=())
        self.assertIsNone(app.allow("b", health=False))
        for _ in range(3):
            self.assertIs(app.allow("a", health=False), app.global_limiter)
        # The backstop recovers: "a" still has its whole budget.
        app.global_limiter = RateLimiter(100, 60, max_keys=1, name="global")
        self.assertEqual(
            [app.allow("a", health=False) for _ in range(3)], [None, None, app.rate_limiter]
        )
        # The same for /healthz.
        app = App(None, None, None, None, None, {"x"}, STATIC_DIR, health_rate_limit=1, health_global_rate_limit=1, trusted_proxies=())
        self.assertIsNone(app.allow("b", health=True))
        self.assertIs(app.allow("a", health=True), app.health_global_limiter)
        app.health_global_limiter = RateLimiter(100, 60, max_keys=1, name="health-global")
        self.assertIsNone(app.allow("a", health=True))

    def test_reserved_connection_serves_healthz_once_and_only_healthz(self) -> None:
        port, app, server = self._serve(max_connections=2, max_per_client=4, header_deadline_s=10)
        release, entered = self._block_search(app)
        busy = []
        for n in (2, 3):
            sock = _connect(port, f"127.0.0.{n}")
            _send(sock, "/api/search?q=hold")
            busy.append(sock)
            self.addCleanup(sock.close)
        for _ in busy:
            self.assertTrue(entered.acquire(timeout=3))
        # Keep-alive /healthz on the reserve: answered, then closed.
        sock = _connect(port, "127.0.0.4")
        self.addCleanup(sock.close)
        _send(sock, "/healthz")
        status, headers, body = _read_response(sock)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(headers["connection"], "close")
        self.assertTrue(_is_closed(sock, 1.0))
        # While the one reserve is held, the next newcomer is refused at accept.
        holder = _connect(port, "127.0.0.5")
        self.addCleanup(holder.close)
        self.assertTrue(_wait(lambda: server._reserved_total == 1))
        self.assertEqual(_get(port, "/healthz", source="127.0.0.6")[0], 503)
        # The held reserve is for /healthz only.
        _send(holder, "/api/search?q=grace")
        status, headers, _ = _read_response(holder)
        self.assertEqual(status, 503)
        self.assertEqual(headers["connection"], "close")
        self.assertTrue(_wait(lambda: server._reserved_total == 0))
        release.set()
        for sock in busy:
            self.assertEqual(_read_response(sock)[0], 200)

    def test_own_healthz_while_own_searches_fill_the_request_slots(self) -> None:
        port, app, server = self._serve(max_connections=16, max_per_client=4, max_requests=2, header_deadline_s=10)
        release, entered = self._block_search(app)
        socks = []
        for _ in range(2):
            sock = _connect(port, "127.0.0.2")
            _send(sock, "/api/search?q=hold")
            socks.append(sock)
            self.addCleanup(sock.close)
        for _ in socks:
            self.assertTrue(entered.acquire(timeout=3))
        self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.2")[0], 503)
        self.assertEqual(_get(port, "/healthz", source="127.0.0.2")[0], 200)
        release.set()
        for sock in socks:
            self.assertEqual(_read_response(sock)[0], 200)
        self.assertTrue(_wait(lambda: server._slots_by_key == {} and server._health_slots_by_key == {}))


# Round 3 of the PR #29 review: when a closing connection gives up its slot.


class SlotReleaseTests(_Served):
    """M1 r3: a slot is held until the last response is flushed, freed before the close."""

    def test_expect_continue_with_close_keeps_its_slot(self) -> None:
        # The CTO's probe scaled down: global cap 4, 2 per peer, held searches,
        # every request with Expect: 100-continue and Connection: close.
        port, app, server = self._serve(max_connections=4, max_per_client=2, max_requests=8, header_deadline_s=10)
        release, entered = self._block_search(app)
        socks = []
        for n in range(2, 7):
            for _ in range(2):
                sock = _connect(port, f"127.0.0.{n}")
                self.addCleanup(sock.close)
                _send(sock, "/api/search?q=hold", {"Expect": "100-continue"}, close=True)
                socks.append(sock)
        running = 0
        while entered.acquire(timeout=0.5):
            running += 1
        # The interim 100 Continue does not free the slot: four searches run.
        self.assertEqual(running, 4)
        self.assertEqual(server._conn_total, 4)
        self.assertEqual(sum(server._conn_by_ip.values()), 4)
        release.set()
        statuses = [_read_final(sock) for sock in socks]
        self.assertEqual(statuses.count(200), 4)
        # The rest were refused: a 503, or closed before their headers were
        # in (evicted for a newcomer, or reset after an accept-time 503).
        self.assertEqual(set(statuses) - {200}, set(statuses) & {503, None})
        self.assertTrue(_wait(lambda: server._conn_total == 0 and server._conn_by_ip == {}))

    def test_a_slow_reader_holds_its_slot_until_the_body_is_flushed(self) -> None:
        port, _app, server = self._serve(max_connections=4, max_per_client=1)
        handler = server.RequestHandlerClass
        real_send = handler._send
        real_setup = handler.setup
        finished = threading.Event()
        real_finish = handler.finish

        def big_send(self, status, body, *args, **kwargs):
            if self.path == "/healthz":
                body = b" " * 4_000_000
            return real_send(self, status, body, *args, **kwargs)

        def small_buffer_setup(self) -> None:
            self.request.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            real_setup(self)

        def noted_finish(self) -> None:
            real_finish(self)
            finished.set()

        handler._send = big_send
        handler.setup = small_buffer_setup
        handler.finish = noted_finish
        self.addCleanup(setattr, handler, "_send", real_send)
        self.addCleanup(setattr, handler, "setup", real_setup)
        self.addCleanup(setattr, handler, "finish", real_finish)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sock.close)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        sock.bind(("127.0.0.2", 0))
        sock.settimeout(5)
        sock.connect(("127.0.0.1", port))
        _send(sock, "/healthz", close=True)
        # Headers are out and the body is stuck behind a client that reads
        # nothing: the connection still counts, so the peer is at its cap.
        self.assertFalse(finished.wait(0.5))
        self.assertEqual(server._conn_total, 1)
        self.assertEqual(server._conn_by_ip, {"127.0.0.2": 1})
        self.assertEqual(_get(port, "/healthz", source="127.0.0.2")[0], 503)
        status, _, body = _read_response(sock)
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 4_000_000)
        self.assertTrue(finished.wait(3))
        self.assertTrue(_wait(lambda: server._conn_total == 0 and server._conn_by_ip == {}))
        self.assertEqual(_get(port, "/healthz", source="127.0.0.2")[0], 200)

    def _assert_freed_before_close(self, server, sock, port: int) -> None:
        # The handler is held after finish: the slot must already be free
        # while the socket is still open.
        self.assertTrue(_wait(lambda: server._conn_total == 0 and server._conn_by_ip == {}, 0.5))
        self.assertFalse(_is_closed(sock, 0.05))
        sock.settimeout(3)
        # The same peer, at its cap of 1, gets straight back in.
        self.assertEqual(_get(port, "/healthz", source="127.0.0.2")[0], 200)

    def test_header_deadline_close_frees_the_slot_before_the_close(self) -> None:
        port, _app, server = self._serve(max_connections=4, max_per_client=1, header_deadline_s=0.3)
        _hold_after_finish(self, server, 1.5)
        sock = _connect(port, "127.0.0.2")
        self.addCleanup(sock.close)
        sock.sendall(b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\n")
        self.assertTrue(_wait(lambda: server._conn_total == 1))
        time.sleep(0.4)
        self._assert_freed_before_close(server, sock, port)

    def test_idle_close_frees_the_slot_before_the_close(self) -> None:
        port, _app, server = self._serve(max_connections=4, max_per_client=1, header_deadline_s=0.3)
        _hold_after_finish(self, server, 1.5)
        sock = _connect(port, "127.0.0.2")
        self.addCleanup(sock.close)
        _send(sock, "/healthz")
        status, headers, _ = _read_response(sock)
        self.assertEqual(status, 200)
        self.assertNotEqual(headers.get("connection"), "close")
        time.sleep(0.4)
        self._assert_freed_before_close(server, sock, port)


class RequestSlotRaceTests(_Served):
    """PR #29 r4 (b): a per-key request slot is held until its response is written.

    The formerly flaky step was a same-key request sent the instant the last
    response was read, before that handler's ``release_slot`` ran. These
    tests hold the handler in that window with an event, not a sleep.
    """

    def test_slot_is_held_until_after_the_response_is_written(self) -> None:
        for path in ("/healthz", "/api/search?q=grace"):
            with self.subTest(path=path):
                port, _app, server = self._serve(max_connections=16, max_per_client=4, max_requests=1)
                gate = _Gate(self, server, "release_slot")
                releases = _Releases(server)
                health = path == "/healthz"
                table = server._health_slots_by_key if health else server._slots_by_key
                sock = _connect(port, "127.0.0.2")
                self.addCleanup(sock.close)
                _send(sock, path)
                self.assertEqual(_read_response(sock)[0], 200)
                # The whole response is read, and its handler has not yet
                # given the slot back: the request is still in flight.
                self.assertTrue(gate.entered.wait(3))
                self.assertEqual(table, {"127.0.0.2": 1})
                status, headers, body = _get(port, path, source="127.0.0.2")
                self.assertEqual(status, 503)
                self.assertEqual(json.loads(body), {"error": "unavailable"})
                self.assertEqual(headers["retry-after"], "1")
                self.assertEqual(headers["connection"], "close")
                # Another key is not affected.
                self.assertEqual(_get(port, path, source="127.0.0.3")[0], 200)
                # Released: the same key gets straight back in, on the old
                # keep-alive connection and on a new one.
                gate.open.set()
                self.assertTrue(gate.done.wait(3))
                # Only this key: 127.0.0.3's release may still be on its way.
                self.assertNotIn("127.0.0.2", table)
                _send(sock, path)
                self.assertEqual(_read_response(sock)[0], 200)
                # The held one, 127.0.0.3's, and the keep-alive request's.
                self.assertTrue(releases.wait_for(3))
                self.assertEqual(table, {})
                self.assertEqual(_get(port, path, source="127.0.0.2")[0], 200)

    def test_in_flight_never_exceeds_the_cap_and_every_slot_comes_back(self) -> None:
        # Production invariant under contention: at most max_requests in
        # flight per key, every refusal is a busy 503 with Retry-After: 1,
        # and no slot leaks. Counted inside acquire and release, so the
        # result does not depend on how the threads interleave.
        port, _app, server = self._serve(max_connections=32, max_per_client=16, max_requests=2)
        lock = threading.Lock()
        state = {"now": 0, "peak": 0, "acquired": 0, "released": 0, "returned": 0}
        real_acquire, real_release = server.acquire_slot, server.release_slot

        def acquire(key, *, health=False):
            ok = real_acquire(key, health=health)
            if ok and not health:
                with lock:
                    state["now"] += 1
                    state["acquired"] += 1
                    state["peak"] = max(state["peak"], state["now"])
            return ok

        def release(key, *, health=False):
            # "now" drops before the real release: the peak can only be
            # undercounted by a request the real table still refuses.
            if not health:
                with lock:
                    state["now"] -= 1
                    state["released"] += 1
            real_release(key, health=health)
            if not health:
                with lock:
                    state["returned"] += 1

        server.acquire_slot, server.release_slot = acquire, release
        start = threading.Barrier(8)
        outcomes = []

        def client() -> None:
            start.wait(3)
            for _ in range(15):
                status, headers, _ = _get(port, "/api/search?q=grace", source="127.0.0.2")
                with lock:
                    outcomes.append((status, headers.get("retry-after")))

        threads = [threading.Thread(target=client) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(len(outcomes), 120)
        self.assertLessEqual(state["peak"], 2)
        self.assertLessEqual(set(outcomes), {(200, None), (503, "1")})
        self.assertIn((200, None), outcomes)
        # Every handler has run release_slot once its last response is out.
        self.assertTrue(_wait(lambda: state["returned"] == state["acquired"]))
        self.assertEqual(state["released"], state["acquired"])
        self.assertEqual(state["now"], 0)
        self.assertEqual(server._slots_by_key, {})

    def test_slot_is_released_when_sending_the_error_response_fails(self) -> None:
        # CTO #29 r4 S1: the search fails, the 500 cannot be written (the
        # client is gone), and the exception leaves _respond_inner. The slot
        # must still come back.
        port, app, server = self._serve(max_connections=16, max_per_client=4, max_requests=1)
        releases = _Releases(server)
        failures = {"search": 0, "send": 0}
        real_search = app.search

        def search(query, *args, **kwargs):
            if query == "boom":
                failures["search"] += 1
                raise RuntimeError("search failed")
            return real_search(query, *args, **kwargs)

        app.search = search
        handler = server.RequestHandlerClass
        real_send_json = handler._send_json

        def send_json(self, status, *args, **kwargs):
            if status == 500:
                failures["send"] += 1
                raise BrokenPipeError("client went away")
            return real_send_json(self, status, *args, **kwargs)

        handler._send_json = send_json
        self.addCleanup(setattr, handler, "_send_json", real_send_json)
        sock = _connect(port, "127.0.0.2")
        self.addCleanup(sock.close)
        _send(sock, "/api/search?q=boom")
        self.assertTrue(releases.wait_for(1))
        self.assertEqual(failures, {"search": 1, "send": 1})
        self.assertEqual(server._slots_by_key, {})
        # The one slot is free: the same key is served, not refused with 503.
        self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.2")[0], 200)


class ReconnectRetryAfterTests(_Served):
    """PR #29 r4 (a): an at-cap peer reconnecting before its closing response's
    connection slot is freed gets 503 with Retry-After: 1."""

    def test_at_cap_reconnect_before_release_gets_retry_after(self) -> None:
        port, _app, server = self._serve(max_connections=4, max_per_client=1)
        # Hold the closing handler after its body is flushed, before it frees
        # its connection slot.
        gate = _Gate(self, server, "closing")
        sock = _connect(port, "127.0.0.2")
        self.addCleanup(sock.close)
        _send(sock, "/healthz", close=True)
        self.assertEqual(_read_response(sock)[0], 200)
        self.assertTrue(gate.entered.wait(3))
        self.assertEqual(server._conn_by_ip, {"127.0.0.2": 1})
        status, headers, body = _get(port, "/healthz", source="127.0.0.2")
        self.assertEqual(status, 503)
        self.assertEqual(headers["retry-after"], "1")
        self.assertEqual(headers["connection"], "close")
        self.assertEqual(json.loads(body), {"error": "unavailable"})
        # No grace period: the slot is the peer's own until it is freed.
        gate.open.set()
        self.assertTrue(gate.done.wait(3))
        self.assertEqual(server._conn_by_ip, {})
        self.assertEqual(_get(port, "/healthz", source="127.0.0.2")[0], 200)


class DocAndScriptTests(unittest.TestCase):
    def test_serve_sh_passes_the_new_settings(self) -> None:
        script = (ROOT / "scripts" / "serve.sh").read_text()
        for name in (
            "PREACHED_TRUSTED_PROXIES",
            "PREACHED_GLOBAL_RATE_LIMIT",
            "PREACHED_HEALTH_RATE_LIMIT",
            "PREACHED_HEALTH_GLOBAL_RATE_LIMIT",
            "PREACHED_MAX_CLIENT_REQUESTS",
            "PREACHED_SCARCE_IDLE_S",
        ):
            self.assertIn(f"pass {name}\n", script)
        self.assertIn("PREACHED_GLOBAL_RATE_LIMIT=${PREACHED_GLOBAL_RATE_LIMIT:-600}", script)
        # Never defaulted to a value: empty means XFF is ignored.
        self.assertNotIn("PREACHED_TRUSTED_PROXIES=", script)

    def test_threat_model_draft_lists_the_gate(self) -> None:
        text = (ROOT / "docs" / "DEPLOY.md").read_text()
        start = text.index("## Threat model (DRAFT, not final)")
        section = text[start : text.index("\n## ", start + 1)]
        for heading in ("### Assets", "### Attackers", "### Entry points", "### Remaining go-public gate items"):
            self.assertIn(heading, section)
        gate = section[section.index("### Remaining go-public gate items") :]
        self.assertLess(gate.index("CTO sign-off"), gate.index("Patrick's approval"))
        self.assertLess(gate.index("Patrick's approval"), gate.index("kill-switch drill"))
        self.assertNotIn("0.0.0.0", section)

    def test_go_public_gate_has_the_round_one_items_before_sign_off(self) -> None:
        text = (ROOT / "docs" / "DEPLOY.md").read_text()
        for heading in ("## Going public", "### Remaining go-public gate items"):
            start = text.index(heading)
            gate = text[start : text.index("\n## ", start + 1) if heading.startswith("## ") else text.index("\n## ", start)]
            sign_off = gate.index("CTO sign-off")
            for item in (
                "RSS fix (#26)",
                "`fallback: false`",
                "group- or world-writable",
                "Stale-bytecode drill",
                "python -m app.server",
                "Audit logging (",
                "journald",
                "tagged",
                "1Password path",
                "Fuzzing",
                "secret scanning in CI",
                "tailscale funnel",
                "/64 IPv6 keying (",
            ):
                with self.subTest(heading=heading, item=item):
                    self.assertLess(gate.index(item), sign_off)
            self.assertNotIn("1.62 GB", gate)
            self.assertIn("PREACHED_TRUSTED_PROXIES=127.0.0.1", gate)
            self.assertIn("direct", gate[gate.index("PREACHED_TRUSTED_PROXIES=127.0.0.1") - 200 :])
        start = text.index("### Known gaps")
        gaps = text[start : text.index("\n### ", start + 1)]
        for item in ("32-address lockout", "65 of 65", "PR #18 behaves the same", "forge `X-Forwarded-For`", "socket peer, not the client"):
            with self.subTest(item=item):
                self.assertIn(item, gaps)
        self.assertNotIn("keyed per address, not per /64", gaps)
        self.assertIn("client IP (the real one behind a trusted proxy), the path and\n  the time are stored", text)
        logs = next(line for line in text.splitlines() if line.startswith("| Logs |"))
        self.assertIn("`peer key method path status`", logs)
        self.assertIn("suppressed=N", logs)

    def test_serve_sh_passes_the_health_reserve(self) -> None:
        script = (ROOT / "scripts" / "serve.sh").read_text()
        self.assertIn("pass PREACHED_HEALTH_RESERVED_CONNECTIONS\n", script)


if __name__ == "__main__":
    unittest.main()
