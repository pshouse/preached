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
        # Cleanups run last-in first-out: stop the server, then close the index.
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
        self.assertEqual(client_key("2001:db8::5", ["2001:db8:1::9"], trusted), "2001:db8:1::9")
        self.assertEqual(client_key("::ffff:192.0.2.9", ["203.0.113.5"], trusted), "192.0.2.9")

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
                status, _, body = _get(port, "/healthz", source=f"127.0.0.{n}")
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)["ok"])
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
        self.assertEqual(_get(port, "/healthz", source="127.0.0.4")[0], 200)
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
        status, _, _ = _get(port, "/healthz", source="127.0.0.4")
        self.assertEqual(status, 503)
        release.set()
        for sock in busy:
            self.assertEqual(_read_response(sock)[0], 200)

    def test_no_churn_between_equal_clients(self) -> None:
        # Every peer holds one: a newcomer is refused, not swapped in.
        port, _app, server = self._serve(max_connections=4, max_per_client=2, header_deadline_s=10, scarce_idle_s=10)
        held = []
        for n in range(2, 6):
            held += self._hold_idle(port, f"127.0.0.{n}", 1, server)
        self.assertTrue(_wait(lambda: server._conn_total == 4))
        self.assertEqual(_get(port, "/healthz", source="127.0.0.6")[0], 503)
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
        self._hold_idle(port, "127.0.0.9", 3, server)
        self.assertTrue(_wait(lambda: server._conn_by_ip.get("127.0.0.9") == 4))
        # Another client through the same proxy, on several more connections.
        others = [
            _get(port, "/healthz", source="127.0.0.9", headers={"X-Forwarded-For": f"198.51.100.{n}"})[0]
            for n in range(20, 24)
        ]
        self.assertEqual(others, [200] * 4)
        release.set()
        self.assertEqual(_read_response(first)[0], 200)
        self.assertTrue(_wait(lambda: server._slots_by_key == {}))

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


if __name__ == "__main__":
    unittest.main()
