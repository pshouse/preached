"""Over-cap 503: a page navigation retries itself; an API client stays on JSON.

A browser that navigates again within a second of the last response is still
over the per-IP cap (#72). The accept thread answers 503 before a handler
starts. Chrome leaves a JSON body on screen. A request whose Accept includes
text/html gets a static HTML page with Retry-After and a meta refresh of that
same delay. Any other request keeps the JSON body exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_exposure import _Served, _connect, _get, _read_response, _send  # noqa: E402

# What Chrome sends on a top-level navigation. text/html is one type in the list.
PAGE_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
API_ACCEPT = "application/json"


class OverCapHtmlTests(_Served):
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
