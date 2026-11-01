"""Listen backlog: a burst of simultaneous connects is not dropped (#77 follow-up).

socketserver listens with a backlog of 5. Fifty clients connecting at once
overflow that queue while the accept thread is busy; the kernel drops the
SYN and the client retries after about 1 s. PreachedServer sets a larger,
bounded request_queue_size. The accept thread is held here until every
client has connected, so the queue depth is what is measured, not timing.

The over-cap 503 also consumes the request bytes it reads, so the close that
follows is a FIN and the client reads the whole 503 (CTO #77 S1-r2).

Loopback only. Every wait is bounded.
"""

from __future__ import annotations

import select
import socket
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from app.server import LISTEN_BACKLOG, MAX_HEADER_BYTES, PreachedServer  # noqa: E402
from test_exposure import _Served, _connect, _read_response, _send  # noqa: E402

SOURCES = 10
PER_SOURCE = 5
CAP = 4
# One SYN retry is about 1 s. Anything under this did not take one.
CONNECT_LIMIT_S = 0.5
# The 503 and 200 arrivals are not the claim; allow a loaded host.
ARRIVAL_LIMIT_S = 2.0
# What the over-cap path reads in its one recv (see _read_over_cap_headers).
READ_BOUND = 65536 + MAX_HEADER_BYTES
ROUNDS = 3


class BacklogSettingTests(unittest.TestCase):
    def test_backlog_is_bounded(self) -> None:
        self.assertEqual(PreachedServer.request_queue_size, LISTEN_BACKLOG)
        self.assertGreater(LISTEN_BACKLOG, SOURCES * PER_SOURCE)
        self.assertLessEqual(LISTEN_BACKLOG, 128)


class BurstTests(_Served):
    def _gate_accept(self, server):
        """Hold accept() until the event is set; connects still complete in the kernel."""
        gate = threading.Event()
        real = server.get_request

        def get_request():
            gate.wait(10)
            return real()

        server.get_request = get_request
        self.addCleanup(gate.set)
        return gate

    def _round(self, port, server, gate_holder):
        gate = gate_holder
        results = [None] * (SOURCES * PER_SOURCE)

        def client(index):
            source = "127.0.0.%d" % (10 + index // PER_SOURCE)
            start = time.monotonic()
            try:
                sock = _connect(port, source)
            except OSError as exc:
                results[index] = (None, time.monotonic() - start, exc)
                return
            results[index] = (sock, time.monotonic() - start, None)

        threads = [threading.Thread(target=client, args=(i,)) for i in range(len(results))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        socks = []
        for index, entry in enumerate(results):
            self.assertIsNotNone(entry, "client %d did not finish" % index)
            sock, took, exc = entry
            self.assertIsNone(exc, "client %d: %r" % (index, exc))
            socks.append(sock)
            self.addCleanup(sock.close)
            self.assertLess(took, CONNECT_LIMIT_S, "client %d connect took %.2f s (SYN retry)" % (index, took))
        worst_connect = max(entry[1] for entry in results)
        release = time.monotonic()
        gate.set()
        # Each source holds CAP connections; the rest are answered 503 at once.
        want = SOURCES * (PER_SOURCE - CAP)
        by_fd = {sock: index for index, sock in enumerate(socks)}
        refused = []
        worst_refusal = ARRIVAL_LIMIT_S
        deadline = release + ARRIVAL_LIMIT_S
        while len(refused) < want and time.monotonic() < deadline:
            readable, _, _ = select.select(list(by_fd), [], [], deadline - time.monotonic())
            for sock in readable:
                refused.append(by_fd.pop(sock))
            if len(refused) >= want:
                worst_refusal = time.monotonic() - release
        pending = list(by_fd.values())
        self.assertEqual(len(refused), SOURCES * (PER_SOURCE - CAP), "over-cap 503s")
        for index in refused:
            socks[index].settimeout(3)
            status, headers, body = _read_response(socks[index])
            self.assertEqual(status, 503)
            self.assertEqual(headers.get("retry-after"), "1")
            self.assertEqual(body, b'{"error":"unavailable"}')
        # The per-client cap held: every source has exactly CAP, none more.
        with server._conn_lock:
            held = dict(server._conn_by_ip)
        for source in range(SOURCES):
            self.assertEqual(held.get("127.0.0.%d" % (10 + source)), CAP, held)
        self.assertEqual(server._conn_total, SOURCES * CAP)
        # The admitted ones are served.
        slowest = 0.0
        for index in pending:
            sock = socks[index]
            sock.settimeout(3)
            start = time.monotonic()
            _send(sock, "/healthz", close=True)
            status, _headers, _body = _read_response(sock)
            slowest = max(slowest, time.monotonic() - start)
            self.assertEqual(status, 200)
        self.assertEqual(len(pending), SOURCES * CAP)
        return worst_connect, worst_refusal, slowest

    def test_fifty_simultaneous_connects_take_no_syn_retry(self) -> None:
        for round_number in range(ROUNDS):
            port, _app, server = self._serve(
                max_connections=64,
                max_per_client=CAP,
                header_deadline_s=30,
                scarce_idle_s=30,
            )
            gate = self._gate_accept(server)
            worst_connect, worst_refusal, slowest = self._round(port, server, gate)
            self.assertLess(worst_refusal, ARRIVAL_LIMIT_S)
            self.assertLess(slowest, ARRIVAL_LIMIT_S)
            print(
                "burst round %d: connect max %.0f ms, 503 max %.0f ms, 200 max %.0f ms"
                % (round_number + 1, worst_connect * 1000, worst_refusal * 1000, slowest * 1000),
                file=sys.stderr,
            )


class FinNotResetTests(_Served):
    @staticmethod
    def _send_all(sock, data) -> None:
        try:
            sock.sendall(data)
        except OSError:
            pass  # the server closed before taking it all; that is the point

    def _full_request_503(self, bare_close: bool, body_size: int) -> None:
        port, _app, server = self._serve(
            max_connections=64,
            max_per_client=1,
            header_deadline_s=30,
            scarce_idle_s=30,
        )
        held = _connect(port, "127.0.0.2")
        self.addCleanup(held.close)
        _send(held, "/healthz")
        self.assertEqual(_read_response(held)[0], 200)
        self.assertEqual(server._conn_by_ip.get("127.0.0.2"), 1)

        # Let the whole request land in the receive buffer before accept()
        # reads it, so any byte left unread at close would force an RST.
        real = server.get_request

        def get_request():
            request, address = real()
            time.sleep(0.3)
            return request, address

        server.get_request = get_request
        if bare_close:
            # socketserver half-closes (FIN) before close(), which hides an
            # RST on Linux. A bare close() isolates the claim under test:
            # nothing is left unread, so close() itself sends a FIN.
            server.shutdown_request = lambda request: request.close()

        body = b"x" * body_size
        head = (
            "POST /api/search HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: application/json\r\n"
            "Content-Length: %d\r\n\r\n" % len(body)
        ).encode("latin-1")
        client = _connect(port, "127.0.0.2")
        self.addCleanup(client.close)
        # The server does not read a body above the bound, so the send can
        # block until the server closes; send from a thread.
        sender = threading.Thread(target=self._send_all, args=(client, head + body))
        sender.start()
        self.addCleanup(sender.join, 10)
        client.settimeout(3)
        # Wait for the server's close to land before reading.
        time.sleep(0.5)
        status, _headers, response = _read_response(client)
        self.assertEqual(status, 503, "no whole 503 (reset before it was read?)")
        self.assertEqual(response, b'{"error":"unavailable"}')
        try:
            rest = client.recv(4096)
        except ConnectionResetError:
            self.fail("the 503 was closed with a reset, not a FIN")
        self.assertEqual(rest, b"")

    def test_a_full_request_with_a_body_gets_the_whole_503_then_fin(self) -> None:
        # Below the read bound: everything is consumed.
        self._full_request_503(bare_close=False, body_size=40000)

    def test_a_body_above_the_peek_size_still_gets_the_whole_503_then_fin(self) -> None:
        # Above the bound the server leaves bytes unread; the FIN must still
        # arrive after the whole 503, not an RST.
        size = 4 * READ_BOUND
        self.assertGreater(size, READ_BOUND)
        self._full_request_503(bare_close=False, body_size=size)

    def test_the_bytes_are_consumed_so_a_bare_close_is_a_fin(self) -> None:
        # Bare close() is a FIN only if nothing is left unread, so stay under the bound.
        self.assertLess(40000, READ_BOUND)
        self._full_request_503(bare_close=True, body_size=40000)


if __name__ == "__main__":
    unittest.main()
