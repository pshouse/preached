"""Over-cap 503: a page navigation retries itself; an API client stays on JSON.

A browser that navigates again within a second of the last response is still
over the per-IP cap (#72). The accept thread answers 503 before a handler
starts. Chrome leaves a JSON body on screen. A request whose Accept includes
text/html gets a static HTML page with Retry-After and a meta refresh of that
same delay. Any other request keeps the JSON body exactly.

The accept thread reads only the bytes already buffered, without waiting
(CTO r1 MF1). Headers that have not all arrived get the JSON 503; a silent
over-cap socket cannot delay the next accept. text/html with q=0 is not
acceptable and gets JSON (MF2). */* is not text/html and gets JSON.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import select
import socket
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from app.server import MAX_HEADER_BYTES, _accept_includes_html, _read_over_cap_headers  # noqa: E402
from test_exposure import _Served, _connect, _get, _read_response, _send  # noqa: E402

# What Chrome sends on a top-level navigation. text/html is one type in the list.
PAGE_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
API_ACCEPT = "application/json"


def _head(*lines: str) -> bytes:
    return ("\r\n".join(("GET / HTTP/1.1", "Host: 127.0.0.1") + lines) + "\r\n\r\n").encode("latin-1")


class AcceptParserTests(unittest.TestCase):
    def test_text_html_in_a_list_counts(self) -> None:
        self.assertTrue(_accept_includes_html(_head("Accept: " + PAGE_ACCEPT)))
        self.assertTrue(_accept_includes_html(_head("Accept: text/html")))

    def test_case_and_whitespace(self) -> None:
        self.assertTrue(_accept_includes_html(_head("ACCEPT: TEXT/HTML")))
        self.assertTrue(_accept_includes_html(_head("accept:application/json ,  Text/Html ;charset=utf-8")))
        self.assertTrue(_accept_includes_html(_head("Accept :\ttext/html\t")))

    def test_every_accept_line_is_read(self) -> None:
        self.assertTrue(_accept_includes_html(_head("Accept: application/json", "Accept: text/html")))
        self.assertTrue(_accept_includes_html(_head("Accept: text/html", "Accept: application/json")))
        self.assertFalse(_accept_includes_html(_head("Accept: application/json", "Accept: image/png")))

    def test_near_misses_do_not_count(self) -> None:
        for line in (
            "Accept: text/htmlx",
            "Accept: xtext/html",
            "Accept: text/html5;q=1",
            "Accept: application/xhtml+xml",
            "Accept-Language: text/html",
            "X-Accept: text/html",
            "Referer: text/html",
            "Accept: text/plain, text/html-fragment",
        ):
            self.assertFalse(_accept_includes_html(_head(line)), line)

    def test_a_folded_continuation_line_is_not_a_header(self) -> None:
        self.assertFalse(_accept_includes_html(_head("X-Note: a", " Accept: text/html")))

    def test_wildcards_stay_json(self) -> None:
        # Pinned (docs/DEPLOY.md): only a client that names text/html gets the page.
        for line in ("Accept: */*", "Accept: text/*", "Accept: */*;q=0.8", "Accept: text/*, */*"):
            self.assertFalse(_accept_includes_html(_head(line)), line)
        self.assertFalse(_accept_includes_html(_head()))

    def test_q_zero_is_not_acceptable(self) -> None:
        for line in (
            "Accept: text/html;q=0",
            "Accept: text/html; q=0.000",
            "Accept: text/html;Q=0",
            "Accept: text/html ; Q = 0.0 ",
            "Accept: text/html;q=0.",
            "Accept: text/html;q=0.00",
            "Accept: text/html;level=1;q=0",
            "Accept: application/json, text/html;q=0",
        ):
            self.assertFalse(_accept_includes_html(_head(line)), line)

    def test_nonzero_q_counts(self) -> None:
        for line in (
            "Accept: text/html;q=0.001",
            "Accept: text/html;q=1",
            "Accept: text/html; q=0.5",
            "Accept: text/html;q=0, text/html;q=0.1",
            "Accept: text/html;qs=0",
        ):
            self.assertTrue(_accept_includes_html(_head(line)), line)

    def test_an_incomplete_header_block_is_json(self) -> None:
        # Split across reads: the blank line has not arrived, so not HTML.
        whole = _head("Accept: text/html")
        self.assertFalse(_accept_includes_html(whole[:-2]))
        self.assertFalse(_accept_includes_html(whole[: whole.index(b"Accept") + 10]))
        self.assertFalse(_accept_includes_html(b""))


class OverCapReadTests(unittest.TestCase):
    def _pair(self):
        ours, theirs = socket.socketpair()
        self.addCleanup(ours.close)
        self.addCleanup(theirs.close)
        return ours, theirs

    def test_a_silent_socket_returns_at_once(self) -> None:
        ours, _theirs = self._pair()
        start = time.monotonic()
        self.assertEqual(_read_over_cap_headers(ours), b"")
        self.assertLess(time.monotonic() - start, 0.05)

    def test_buffered_bytes_are_returned(self) -> None:
        ours, theirs = self._pair()
        theirs.sendall(_head("Accept: text/html"))
        self.assertTrue(_accept_includes_html(_read_over_cap_headers(ours)))

    def test_a_split_header_reads_only_the_first_part(self) -> None:
        # The rest arrives later; the accept thread does not wait for it.
        ours, theirs = self._pair()
        whole = _head("Accept: text/html")
        theirs.sendall(whole[:20])
        start = time.monotonic()
        data = _read_over_cap_headers(ours)
        self.assertLess(time.monotonic() - start, 0.05)
        self.assertEqual(data, whole[:20])
        self.assertFalse(_accept_includes_html(data))

    def test_the_read_is_bounded(self) -> None:
        ours, theirs = self._pair()
        bound = 65536 + MAX_HEADER_BYTES
        theirs.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * bound)
        ours.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * bound)
        theirs.sendall(b"x" * (2 * bound))
        data = _read_over_cap_headers(ours)
        self.assertGreater(len(data), 0)
        self.assertLessEqual(len(data), bound)
        self.assertFalse(_accept_includes_html(data))

    def test_a_closed_peer_is_json(self) -> None:
        ours, theirs = self._pair()
        theirs.close()
        self.assertEqual(_read_over_cap_headers(ours), b"")


class OverCapHtmlTests(_Served):
    def _serve(self, **kwargs):
        port, app, server = super()._serve(**kwargs)
        # A browser sends its request right after the handshake. Here the
        # accept thread waits for those bytes before it reads, so whether
        # they beat accept() is not a race in the test. The real server
        # never waits (see test_headers_not_yet_arrived_get_json).
        real = server.get_request

        def get_request():
            request, address = real()
            select.select([request], [], [], 2)
            return request, address

        server.get_request = get_request
        return port, app, server

    def _over_cap(self, path: str, accept: str):
        # One idle keep-alive holds the only per-IP slot. The next connection
        # is inside the quiet second, so it is the accept-thread 503.
        port, _app, server = self._serve(
            max_connections=4,
            max_per_client=1,
            header_deadline_s=30,
            scarce_idle_s=30,
        )
        held = _connect(port, "127.0.0.2")
        self.addCleanup(held.close)
        _send(held, "/healthz")
        self.assertEqual(_read_response(held)[0], 200)
        self.assertEqual(server._conn_by_ip.get("127.0.0.2"), 1)
        return _get(port, path, source="127.0.0.2", headers={"Accept": accept})

    def test_html_navigation_gets_a_refreshing_page(self) -> None:
        status, headers, body = self._over_cap("/?q=grace", PAGE_ACCEPT)
        self.assertEqual(status, 503)
        self.assertEqual(headers.get("content-type"), "text/html; charset=utf-8")
        self.assertEqual(headers.get("retry-after"), "1")
        self.assertEqual(headers.get("connection"), "close")
        self.assertEqual(headers.get("cache-control"), "no-store")
        text = body.decode("utf-8")
        self.assertIn('<meta http-equiv="refresh" content="1">', text)
        self.assertIn(f'content="{headers["retry-after"]}"', text)
        # The page is static. The query, the peer, and the JSON error stay out.
        self.assertNotIn("grace", text)
        self.assertNotIn("127.0.0.2", text)
        self.assertNotIn('{"error"', text)
        self.assertNotIn("<script", text.lower())
        self.assertNotIn("http://", text)
        self.assertNotIn("https://", text)

    def test_api_json_request_keeps_the_json_503(self) -> None:
        status, headers, body = self._over_cap("/api/search?q=grace", API_ACCEPT)
        self.assertEqual(status, 503)
        self.assertEqual(headers.get("content-type"), "application/json; charset=utf-8")
        self.assertEqual(headers.get("retry-after"), "1")
        self.assertEqual(headers.get("connection"), "close")
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertEqual(body, b'{"error":"unavailable"}')
        self.assertNotIn(b"text/html", body)
        self.assertNotIn(b"refresh", body)

    def test_q_zero_html_gets_json(self) -> None:
        for accept in ("text/html;q=0", "text/html; q=0.000", "text/html;Q=0"):
            status, headers, body = self._over_cap("/", accept)
            self.assertEqual(status, 503, accept)
            self.assertEqual(headers.get("content-type"), "application/json; charset=utf-8", accept)
            self.assertEqual(body, b'{"error":"unavailable"}', accept)

    def test_wildcard_gets_json(self) -> None:
        status, headers, body = self._over_cap("/", "*/*")
        self.assertEqual(status, 503)
        self.assertEqual(headers.get("content-type"), "application/json; charset=utf-8")
        self.assertEqual(body, b'{"error":"unavailable"}')


class OverCapNoWaitTests(_Served):
    def _hold_slot(self, source: str):
        port, _app, server = self._serve(
            max_connections=64,
            max_per_client=1,
            header_deadline_s=30,
            scarce_idle_s=30,
        )
        held = _connect(port, source)
        self.addCleanup(held.close)
        _send(held, "/healthz")
        self.assertEqual(_read_response(held)[0], 200)
        return port, server

    def test_headers_not_yet_arrived_get_json(self) -> None:
        # Documented: a page navigation whose headers had not arrived at
        # accept() gets the JSON 503, not the page.
        port, _server = self._hold_slot("127.0.0.2")
        sock = _connect(port, "127.0.0.2")
        self.addCleanup(sock.close)
        status, headers, body = _read_response(sock)
        self.assertEqual(status, 503)
        self.assertEqual(headers.get("content-type"), "application/json; charset=utf-8")
        self.assertEqual(headers.get("retry-after"), "1")
        self.assertEqual(body, b'{"error":"unavailable"}')
        try:
            _send(sock, "/", {"Accept": PAGE_ACCEPT})
        except OSError:
            pass  # already closed by the server

    def test_silent_over_cap_sockets_do_not_delay_the_next_client(self) -> None:
        port, server = self._hold_slot("127.0.0.2")
        # Room in the listen queue for all of them, so the kernel never
        # drops a handshake and only the accept thread can add delay.
        server.socket.listen(128)
        silent = []
        for _ in range(20):
            sock = _connect(port, "127.0.0.2")
            self.addCleanup(sock.close)
            silent.append(sock)
        start = time.monotonic()
        legit = socket.create_connection(("127.0.0.1", port), timeout=5, source_address=("127.0.0.3", 0))
        self.addCleanup(legit.close)
        legit.settimeout(5)
        _send(legit, "/healthz", close=True)
        status, _headers, _body = _read_response(legit)
        elapsed = time.monotonic() - start
        self.assertEqual(status, 200, "no response within 5 s")
        self.assertLess(elapsed, 0.1)
        # Each silent socket was answered and closed at once, with Retry-After.
        for sock in silent:
            sock.settimeout(0.5)
            status, headers, body = _read_response(sock)
            self.assertEqual(status, 503)
            self.assertEqual(headers.get("retry-after"), "1")
            self.assertEqual(body, b'{"error":"unavailable"}')
            self.assertEqual(sock.recv(1), b"")
