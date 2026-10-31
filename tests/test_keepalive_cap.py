"""Idle keep-alive must not sit on the per-IP connection cap.

A finished HTTP/1.1 response leaves the socket open, and that socket counts
toward the per-IP cap. Once it has been quiet for ``KEEPALIVE_IDLE_S``, a
new connection from the same IP takes it. A second search therefore
finishes well under the old header-deadline stall. Requests that are
actually in flight are not taken, so a flood still stops at the cap.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from app.server import KEEPALIVE_IDLE_S  # noqa: E402
from test_exposure import _Served, _connect, _get, _is_closed, _read_response, _send, _wait  # noqa: E402

# The old stall is the header deadline (15s), and a browser left on the
# refused page until someone closes the first tab. The search after the
# quiet period has to finish inside this.
BOUND_S = 3.0


class KeepAliveCapTests(_Served):
    def test_idle_keepalive_frees_the_per_ip_slot(self) -> None:
        self.assertLess(KEEPALIVE_IDLE_S + 1.0, BOUND_S)
        # The header deadline stays long, so a quiet socket is still held
        # for the whole test unless the keep-alive hand-over runs.
        port, _app, server = self._serve(
            max_connections=8,
            max_per_client=1,
            header_deadline_s=30,
            scarce_idle_s=30,
        )
        held = _connect(port, "127.0.0.2")
        self.addCleanup(held.close)
        _send(held, "/healthz")
        status, headers, _body = _read_response(held)
        self.assertEqual(status, 200)
        self.assertNotEqual(headers.get("connection"), "close")
        self.assertEqual(server._conn_by_ip.get("127.0.0.2"), 1)

        # Quiet-period probe: must run within 1 s of the response, while
        # the keep-alive is still inside KEEPALIVE_IDLE_S.
        self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.2")[0], 503)
        self.assertFalse(_is_closed(held, 0.05))

        time.sleep(KEEPALIVE_IDLE_S + 0.4)
        started = time.monotonic()
        status, _headers, body = _get(port, "/api/search?q=grace", source="127.0.0.2")
        elapsed = time.monotonic() - started
        self.assertEqual(status, 200, body)
        self.assertLess(elapsed, 1.0)
        self.assertIn("results", json.loads(body))
        # The idle keep-alive was the socket handed over.
        self.assertTrue(_is_closed(held, 1.0))
        self.assertLess(KEEPALIVE_IDLE_S + 0.4 + elapsed, BOUND_S)

    def test_an_active_flood_still_stops_at_the_cap(self) -> None:
        # In-flight searches are not idle keep-alives. They hold the cap
        # past KEEPALIVE_IDLE_S, and the next search is refused.
        port, app, server = self._serve(
            max_connections=8,
            max_per_client=2,
            header_deadline_s=30,
            scarce_idle_s=30,
        )
        release, entered = self._block_search(app)
        busy = []
        for _ in range(2):
            sock = _connect(port, "127.0.0.2")
            self.addCleanup(sock.close)
            _send(sock, "/api/search?q=hold")
            busy.append(sock)
        for _ in busy:
            self.assertTrue(entered.acquire(timeout=3))
        self.assertEqual(server._conn_by_ip.get("127.0.0.2"), 2)
        refused, headers, body = _get(port, "/api/search?q=grace", source="127.0.0.2")
        self.assertEqual(refused, 503)
        self.assertEqual(headers.get("retry-after"), "1")
        self.assertEqual(json.loads(body), {"error": "unavailable"})
        time.sleep(KEEPALIVE_IDLE_S + 0.4)
        self.assertEqual(_get(port, "/api/search?q=grace", source="127.0.0.2")[0], 503)
        self.assertEqual(server._conn_by_ip.get("127.0.0.2"), 2)
        for sock in busy:
            self.assertFalse(_is_closed(sock, 0.05))
        release.set()
        for sock in busy:
            self.assertEqual(_read_response(sock)[0], 200)

    def test_a_partial_header_socket_is_not_handed_over(self) -> None:
        # Mid-headers past the quiet second is still not takeable. Dropping
        # ``conn.reading`` from ``_takeable_idle`` lets the newcomer in.
        port, _app, server = self._serve(
            max_connections=8,
            max_per_client=1,
            header_deadline_s=30,
            scarce_idle_s=30,
        )
        held = _connect(port, "127.0.0.2")
        self.addCleanup(held.close)
        held.sendall(b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\n")
        self.assertTrue(_wait(lambda: any(c.reading for c in server._conns.values())))
        time.sleep(KEEPALIVE_IDLE_S + 0.4)
        status, headers, body = _get(port, "/api/search?q=grace", source="127.0.0.2")
        self.assertEqual(status, 503, body)
        self.assertEqual(headers.get("retry-after"), "1")
        self.assertFalse(_is_closed(held, 0.05))
        held.sendall(b"\r\n")
        self.assertEqual(_read_response(held)[0], 200)

    def test_a_busy_peer_cannot_close_another_peers_idle_socket(self) -> None:
        # The global cap is not full, so the "two more" rule is not what
        # keeps this socket. Dropping ``conn.holder != holder`` lets the
        # peer that is already at its cap close it.
        port, app, server = self._serve(
            max_connections=8,
            max_per_client=2,
            header_deadline_s=30,
            scarce_idle_s=30,
        )
        idle = _connect(port, "127.0.0.2")
        self.addCleanup(idle.close)
        _send(idle, "/healthz")
        self.assertEqual(_read_response(idle)[0], 200)
        time.sleep(KEEPALIVE_IDLE_S + 0.4)
        release, entered = self._block_search(app)
        busy = []
        for _ in range(2):
            sock = _connect(port, "127.0.0.3")
            self.addCleanup(sock.close)
            _send(sock, "/api/search?q=hold")
            busy.append(sock)
        for _ in busy:
            self.assertTrue(entered.acquire(timeout=3))
        self.assertEqual(server._conn_by_ip.get("127.0.0.3"), 2)
        status, headers, body = _get(port, "/api/search?q=grace", source="127.0.0.3")
        self.assertEqual(status, 503, body)
        self.assertEqual(headers.get("retry-after"), "1")
        self.assertFalse(_is_closed(idle, 0.05))
        _send(idle, "/healthz")
        self.assertEqual(_read_response(idle)[0], 200)
        release.set()
        for sock in busy:
            self.assertEqual(_read_response(sock)[0], 200)

    def test_hand_over_leaves_the_per_ip_count_at_the_cap(self) -> None:
        # Dropping ``held -= 1`` stores cap + 1 and leaves a ghost slot
        # after every socket has closed.
        port, _app, server = self._serve(
            max_connections=8,
            max_per_client=1,
            header_deadline_s=30,
            scarce_idle_s=30,
        )
        held = _connect(port, "127.0.0.2")
        self.addCleanup(held.close)
        _send(held, "/healthz")
        self.assertEqual(_read_response(held)[0], 200)
        self.assertEqual(server._conn_by_ip.get("127.0.0.2"), 1)
        time.sleep(KEEPALIVE_IDLE_S + 0.4)
        newcomer = _connect(port, "127.0.0.2")
        self.addCleanup(newcomer.close)
        _send(newcomer, "/healthz")
        status, _headers, body = _read_response(newcomer)
        self.assertEqual(status, 200, body)
        self.assertTrue(_is_closed(held, 1.0))
        self.assertEqual(
            server._conn_by_ip["127.0.0.2"], server.max_connections_per_client
        )
        newcomer.close()
        self.assertTrue(_wait(lambda: "127.0.0.2" not in server._conn_by_ip))
        self.assertEqual(server._conn_by_ip.get("127.0.0.2", 0), 0)

    def test_a_reserved_healthz_socket_is_never_handed_over(self) -> None:
        # Admitted over the global cap and still waiting for its one
        # request. Dropping ``conn.reserved`` hands that socket over.
        port, app, server = self._serve(
            max_connections=1,
            max_per_client=2,
            header_deadline_s=30,
            scarce_idle_s=30,
        )
        server.health_reserved = 1
        release, entered = self._block_search(app)
        busy = _connect(port, "127.0.0.2")
        self.addCleanup(busy.close)
        _send(busy, "/api/search?q=hold")
        self.assertTrue(entered.acquire(timeout=3))
        reserved = _connect(port, "127.0.0.2")
        self.addCleanup(reserved.close)
        self.assertTrue(_wait(lambda: any(c.reserved for c in server._conns.values())))
        time.sleep(KEEPALIVE_IDLE_S + 0.4)
        status, _headers, body = _get(port, "/healthz", source="127.0.0.2")
        self.assertEqual(status, 503, body)
        self.assertFalse(_is_closed(reserved, 0.05))
        _send(reserved, "/healthz")
        status, headers, _body = _read_response(reserved)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("connection"), "close")
        release.set()
        self.assertEqual(_read_response(busy)[0], 200)
