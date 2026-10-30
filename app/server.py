"""Search API and the mobile page.

Stdlib HTTP only. The embedding model loads once, on CPU. If it fails, search
falls back to BM25 and every search response says so. There are no write routes.

Security choices:
- static files are an allowlist, not a directory
- CSP has no inline script and no CDN
- the Host header must match the allowlist
- request target, header, and body size are limited; the socket times out
- clients never receive a traceback
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from preached import env  # noqa: E402, F401
from preached.abstain import floor_for, search_with_confidence  # noqa: E402
from preached.library import (  # noqa: E402
    CHURCH_EMPTY,
    CHURCH_LABEL,
    CLASSIC_LABEL,
    church_index_matches,
    is_sample_library,
    read_label,
    resolve_church_path,
)
from preached.models import DEFAULT_MODEL, MODELS  # noqa: E402
from preached.paths import INDEX_DIR, INDEX_PATH  # noqa: E402
from preached.search import (  # noqa: E402
    Searcher,
    display_excerpt,
    row_value,
    _optional_int,
    _text_or_none,
)
from preached.store import EmbeddingMismatch, open_readonly  # noqa: E402
from preached.youtube.listing import public_audio_url  # noqa: E402

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
PAGE_FILE = STATIC_DIR / "index.html"

STATIC_TYPES = {
    "app.js": "text/javascript; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "favicon.svg": "image/svg+xml",
}

# archive.org redirects into *.archive.org. The player streams that directly.
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self'",
        "media-src 'self' https://archive.org https://*.archive.org",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

MODES = {"hybrid", "bm25", "dense"}
LIBRARY = "wesley"
# One process serves one library file. The slug is the file name under
# /cache/index. The default stays wesley so the existing page keeps working.
LIBRARY_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_TARGET = 2048
MAX_BODY = 4096
REQUEST_TIMEOUT_S = 15
# Wesley ids are lowercase slugs (wesley-001), at most 64 characters. A
# YouTube video id is 11 characters and case-sensitive. Dots and slashes are
# not in either form, so a path cannot be an id.
SERMON_ID = re.compile(r"^(?:[a-z0-9][a-z0-9-]{0,63}|[A-Za-z0-9_-]{11})$")

FALLBACK_NOTE = "Embedding model failed to load; results are BM25 only."
BM25_ONLY_NOTE = "Embeddings are not loaded; results are BM25 only."
STALE_NOTE = "Stored passage vectors do not match the configured model; results are BM25 only."

RESULT_FIELDS = (
    "chunk_id",
    "chunk_ids",
    "sermon_id",
    "sermon_number",
    "sermon_title",
    "scripture",
    "text",
    "start_s",
    "end_s",
    "audio_url",
    "reader",
    "text_source",
    "source_url",
    "score",
)


class BadRequest(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def rss_bytes() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def hostname_of(value: str) -> str:
    text = value.strip().lower()
    if not text:
        return ""
    if text.startswith("["):
        end = text.find("]")
        return text[1:end] if end > 1 else ""
    if ":" in text:
        host, _, port = text.rpartition(":")
        if port.isdigit():
            return host
    return text


def static_name(path: str) -> str | None:
    """Allowlist lookup. Encoded dots, slashes, and extra segments are rejected."""
    prefix = "/static/"
    if not path.startswith(prefix):
        return None
    raw = path[len(prefix) :]
    if not raw or raw.endswith("/"):
        return None
    if any(token in raw for token in ("/", "\\", "\x00", "..", "%")):
        return None
    if raw not in STATIC_TYPES:
        return None
    return raw


def _first(args: dict, name: str) -> str | None:
    values = args.get(name)
    if not values:
        return None
    return values[0]


def parse_search_args(
    args: dict, *, library: str = LIBRARY, libraries: list[str] | None = None
) -> tuple[str, int, str, str]:
    """Query, k, mode, and the library slug this search is scoped to.

    ``libraries`` is the files this process has open (classic, then church).
    A slug outside that list is a 400. The default slug is the classic one,
    so a request that omits ``library`` stays on the library the page already
    asks for.
    """
    raw_q = _first(args, "q")
    if raw_q is None:
        raise BadRequest("q is required")
    query = raw_q.strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in query):
        raise BadRequest("q has unsupported characters")
    if not query or len(query) > 300:
        raise BadRequest("q must be 1 to 300 characters")

    raw_k = _first(args, "k")
    if raw_k is None or raw_k.strip() == "":
        k = 10
    else:
        token = raw_k.strip()
        if not re.fullmatch(r"[0-9]+", token):
            raise BadRequest("k must be an integer from 1 to 25")
        k = int(token)
        if k < 1 or k > 25:
            raise BadRequest("k must be an integer from 1 to 25")

    raw_mode = _first(args, "mode")
    mode = "hybrid" if raw_mode is None or raw_mode.strip() == "" else raw_mode.strip()
    if mode not in MODES:
        raise BadRequest("mode must be hybrid, bm25, or dense")

    allowed = list(libraries) if libraries else [library]
    raw_library = _first(args, "library")
    chosen = allowed[0] if raw_library is None or raw_library.strip() == "" else raw_library.strip()
    if chosen not in allowed:
        raise BadRequest("library must be " + " or ".join(allowed))
    return query, k, mode, chosen


def hit_dict(hit) -> dict:
    payload = {
        "chunk_id": hit.chunk_id,
        "chunk_ids": hit.chunk_ids,
        "sermon_id": hit.sermon_id,
        "sermon_number": hit.sermon_number,
        "sermon_title": hit.sermon_title,
        "scripture": hit.scripture,
        "text": display_excerpt(hit.text),
        "start_s": hit.start_s,
        "end_s": hit.end_s,
        "audio_url": public_audio_url(hit.audio_url),
        "reader": hit.reader,
        "text_source": hit.text_source,
        "source_url": hit.source_url,
        "score": float(hit.score),
    }
    return {key: payload[key] for key in RESULT_FIELDS}


def _side_body(
    payload: dict,
    *,
    library: str,
    label: str,
    sample: bool,
    present: bool,
    empty_message: str | None,
) -> dict:
    """One column of /api/side. Hit fields are the same object ``search`` returns."""
    results = payload["results"]
    empty = not results
    return {
        "library": library,
        "label": label,
        "sample": sample,
        "present": present,
        "empty": empty,
        "message": empty_message if empty and empty_message else None,
        "mode": payload["mode"],
        "results": results,
        "note": payload["note"],
        "abstain": payload["abstain"],
        "confidence": payload["confidence"],
    }


def default_loader(connection, model_key: str):
    """Load Granite on CPU. The GPU stays with the Whisper job."""
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    from preached.embed import encode_query, load_model, unload

    spec = MODELS[model_key]
    # Check the stored vectors' fingerprint before paying for the weights.
    searcher = Searcher(connection, model=model_key)
    loaded = load_model(spec, device="cpu", batch_size=1)

    def encode(query: str):
        return encode_query(loaded, query)

    return searcher, encode


def load_search(connection, model_key: str, *, bm25_only: bool = False, loader=None):
    """Return (searcher, encode_or_none, fallback_note_or_none)."""
    if bm25_only:
        return Searcher(connection), None, None
    loader = loader or default_loader
    try:
        searcher, encode = loader(connection, model_key)
    except EmbeddingMismatch:
        # Never pair new query vectors with old document vectors.
        logging.exception("stored vectors do not match search/models.toml; serving BM25 only")
        return Searcher(connection), None, STALE_NOTE
    except Exception:
        logging.exception("embedding model unavailable; serving BM25 only")
        return Searcher(connection), None, FALLBACK_NOTE
    return searcher, encode, None


def load_church_searcher(connection, model_key: str, *, bm25_only: bool):
    """Searcher for the church file, plus a note when that side is BM25 only.

    A bad or missing church vector file does not take the classic side down
    with it. The church column falls back to keyword search and says so.
    """
    if bm25_only:
        return Searcher(connection), None
    try:
        return Searcher(connection, model=model_key), None
    except EmbeddingMismatch:
        logging.exception("church vectors do not match search/models.toml; that side is BM25 only")
        return Searcher(connection), STALE_NOTE
    except Exception:
        logging.exception("church vectors unavailable; that side is BM25 only")
        return Searcher(connection), STALE_NOTE


class App:
    def __init__(
        self,
        connection,
        searcher,
        encode,
        fallback_note,
        model_name,
        hosts,
        static_dir,
        floor=None,
        library: str = LIBRARY,
        church_connection=None,
        church_searcher=None,
        church_library: str | None = None,
        church_label: str | None = None,
        church_sample: bool | None = None,
        church_note: str | None = None,
        classic_label: str | None = None,
    ):
        self.connection = connection
        self.searcher = searcher
        self.encode = encode
        self.fallback_note = fallback_note
        self.model_name = model_name if encode is not None else None
        # Abstain floor for this model (search/abstain.toml). None: never abstain
        # on dense evidence; see preached.abstain.
        self.floor = floor if encode is not None else None
        self.hosts = frozenset(host.lower() for host in hosts)
        self.static_dir = Path(static_dir)
        self.lock = threading.Lock()
        self.library = library
        self.classic_label = classic_label or read_label(connection) or (
            CLASSIC_LABEL if library == LIBRARY else library
        )
        # A church side exists only when both the file and its searcher are here.
        # Missing is the empty state, not a failed server.
        if church_searcher is None or not church_library:
            self.church_connection = None
            self.church_searcher = None
            self.church_library = None
            self.church_label = CHURCH_LABEL
            self.church_sample = False
            self.church_note = None
        else:
            self.church_connection = church_connection
            self.church_searcher = church_searcher
            self.church_library = church_library
            self.church_label = church_label or read_label(church_connection) or CHURCH_LABEL
            detected = is_sample_library(church_library, church_connection)
            self.church_sample = detected if church_sample is None else bool(church_sample) or detected
            self.church_note = church_note

    def host_allowed(self, header_value: str) -> bool:
        return hostname_of(header_value) in self.hosts

    def health(self) -> dict:
        with self.lock:
            count = int(self.connection.execute("SELECT count(*) FROM chunks").fetchone()[0])
        return {
            "ok": True,
            "library": self.library,
            "chunks": count,
            "model": self.model_name,
            "fallback": self.fallback_note is not None,
            "dense": self.encode is not None,
            "abstain_calibrated": self.floor is not None,
            "church": self.church_library,
        }

    def library_names(self) -> list[str]:
        """Slugs this process will search. Classic first, then the church file."""
        names = [self.library]
        if self.church_library and self.church_library not in names:
            names.append(self.church_library)
        return names

    def search(self, query: str, k: int, mode: str, *, library: str | None = None) -> dict:
        """Search one open library. ``library`` defaults to the classic file."""
        chosen = self.library if library is None else library
        if chosen == self.library:
            searcher = self.searcher
            side_note = None
        elif chosen == self.church_library and self.church_searcher is not None:
            searcher = self.church_searcher
            side_note = self.church_note
        else:
            raise BadRequest("library must be " + " or ".join(self.library_names()))
        started = time.perf_counter()
        with self.lock:
            note = None
            effective = mode
            # No query encoder, or this file has no usable vectors: keyword
            # search, same rule as a BM25-only process. The other side is
            # unaffected because it has its own searcher.
            if self.encode is None or searcher._matrix is None:
                if self.encode is None and self.fallback_note:
                    note = self.fallback_note
                elif side_note:
                    note = side_note
                elif mode != "bm25":
                    note = BM25_ONLY_NOTE
                effective = "bm25"
            vector = None if effective == "bm25" else self.encode(query)
            kept, confidence = search_with_confidence(
                searcher, query, vector, effective, k, self.floor
            )
        return {
            "query": query,
            "mode": effective,
            "took_ms": int(round((time.perf_counter() - started) * 1000)),
            "results": [hit_dict(hit) for hit in kept],
            "note": note,
            # True when the page should say nothing strong was found. The
            # closest passages stay in results so a person can still look.
            "abstain": confidence.abstain,
            "confidence": confidence.as_dict(),
        }

    def side(self, query: str, k: int, mode: str) -> dict:
        """Top ``k`` hits from the classic library and from your church.

        Each side uses the same abstain rule as ``search``. A missing church
        file is a 200 with an empty church side, not an error.
        """
        started = time.perf_counter()
        classic = _side_body(
            self.search(query, k, mode, library=self.library),
            library=self.library,
            label=self.classic_label,
            sample=False,
            present=True,
            empty_message=None,
        )
        if self.church_searcher is None:
            church = {
                "library": None,
                "label": CHURCH_LABEL,
                "sample": False,
                "present": False,
                "empty": True,
                "message": CHURCH_EMPTY,
                "mode": None,
                "results": [],
                "note": None,
                "abstain": False,
                "confidence": None,
            }
        else:
            church = _side_body(
                self.search(query, k, mode, library=self.church_library),
                library=self.church_library,
                label=self.church_label,
                sample=self.church_sample,
                present=True,
                empty_message=CHURCH_EMPTY,
            )
        return {
            "query": query,
            "mode": mode,
            "k": k,
            "took_ms": int(round((time.perf_counter() - started) * 1000)),
            "classic": classic,
            "church": church,
        }

    def sermon(self, sermon_id: str) -> dict | None:
        if not SERMON_ID.fullmatch(sermon_id):
            return None
        with self.lock:
            rows = list(
                self.connection.execute(
                    "SELECT * FROM chunks WHERE sermon_id = ? ORDER BY rowid",
                    (sermon_id,),
                )
            )
        if not rows:
            return None
        first = rows[0]
        audio_url = None
        reader = None
        for row in rows:
            if audio_url is None:
                audio_url = _text_or_none(row_value(row, "audio_url"))
            if reader is None:
                reader = _text_or_none(row_value(row, "reader"))
            if audio_url and reader:
                break
        return {
            "sermon_id": sermon_id,
            "sermon_number": _optional_int(row_value(first, "sermon_number")),
            "sermon_title": first["sermon_title"],
            "scripture": _text_or_none(row_value(first, "scripture")),
            "source_url": _text_or_none(row_value(first, "source_url")),
            "audio_url": audio_url,
            "reader": reader,
        }


def build_app(
    connection,
    *,
    model_key: str,
    bm25_only: bool,
    hosts,
    static_dir,
    loader=None,
    floor=None,
    library: str = LIBRARY,
    church_connection=None,
    church_library: str | None = None,
    church_label: str | None = None,
    church_sample: bool | None = None,
) -> App:
    """``floor`` overrides search/abstain.toml (tests); None reads the file."""
    searcher, encode, note = load_search(
        connection,
        model_key,
        bm25_only=bm25_only,
        loader=loader,
    )
    if floor is None and encode is not None:
        try:
            # Keyed on the query embedder too: a floor fitted on torch fp32
            # does not apply to another backend or variant.
            floor = floor_for(
                model_key,
                backend=getattr(encode, "backend", "torch"),
                variant=getattr(encode, "variant", None),
            )
        except Exception:
            # floor_for already treats a bad file as no floor; this guard
            # keeps any other surprise from stopping the server.
            logging.exception("abstain calibration unusable; abstain floor disabled")
            floor = None
    church_searcher = None
    church_note = None
    if church_connection is not None and church_library:
        church_searcher, church_note = load_church_searcher(
            church_connection, model_key, bm25_only=bm25_only or encode is None
        )
    return App(
        floor=floor,
        connection=connection,
        searcher=searcher,
        encode=encode,
        fallback_note=note,
        model_name=model_key,
        hosts=hosts,
        static_dir=static_dir,
        library=library,
        church_connection=church_connection,
        church_searcher=church_searcher,
        church_library=church_library,
        church_label=church_label,
        church_sample=church_sample,
        church_note=church_note,
    )


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "Preached"
        sys_version = ""
        timeout = REQUEST_TIMEOUT_S

        def log_message(self, fmt, *args):
            logging.info("%s %s", self.address_string(), fmt % args)

        def version_string(self):
            return "Preached"

        def send_error(self, code, message=None, explain=None):
            """Fixed JSON. The request line is not echoed back to the client."""
            try:
                self.log_error("code %s, message %s", code, message)
            except Exception:
                logging.exception("error while logging a rejected request")
            self.close_connection = True
            if code in (413, 414, 431):
                text = "request too large"
            else:
                text = "bad request"
            body = json.dumps({"error": text}).encode("utf-8")
            self.send_response(int(code))
            self._security_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            if getattr(self, "command", "") != "HEAD":
                self.wfile.write(body)

        def _security_headers(self) -> None:
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")

        def _send(self, status: int, body: bytes, content_type: str, include_body: bool) -> None:
            self._started = True
            self.send_response(status)
            self._security_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if include_body:
                self.wfile.write(body)

        def _send_json(self, status: int, payload: dict, include_body: bool) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8", include_body)

        def _limits_and_host(self) -> None:
            if len(self.path) > MAX_TARGET:
                raise BadRequest("request too large", 414)
            if self.headers.get("Transfer-Encoding"):
                raise BadRequest("request too large", 413)
            raw_length = self.headers.get("Content-Length")
            if raw_length is not None:
                try:
                    length = int(raw_length)
                except ValueError as exc:
                    raise BadRequest("bad content length") from exc
                if length > MAX_BODY:
                    raise BadRequest("request too large", 413)
            hosts = self.headers.get_all("Host") or []
            if len(hosts) != 1 or not app.host_allowed(hosts[0]):
                raise BadRequest("host not allowed", 421)

        def _route(self, include_body: bool) -> None:
            self._limits_and_host()
            parsed = urlsplit(self.path)
            path = parsed.path or "/"
            if path == "/":
                self._send_page(include_body)
                return
            if path == "/healthz":
                self._send_json(200, app.health(), include_body)
                return
            if path in ("/api/search", "/api/side"):
                try:
                    args = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=32)
                except ValueError as exc:
                    raise BadRequest("request too large", 414) from exc
                query, k, mode, chosen = parse_search_args(args, libraries=app.library_names())
                if path == "/api/side":
                    # Both columns. ``library`` is still checked so a bad slug
                    # cannot widen what this process is willing to open.
                    self._send_json(200, app.side(query, k, mode), include_body)
                else:
                    self._send_json(200, app.search(query, k, mode, library=chosen), include_body)
                return
            if path.startswith("/api/sermon/"):
                self._send_sermon(path[len("/api/sermon/") :], include_body)
                return
            if path.startswith("/static/"):
                self._send_static(path, include_body)
                return
            self._send_json(404, {"error": "not found"}, include_body)

        def _send_page(self, include_body: bool) -> None:
            try:
                data = PAGE_FILE.read_bytes()
            except OSError:
                self._send_json(404, {"error": "not found"}, include_body)
                return
            self._send(200, data, "text/html; charset=utf-8", include_body)

        def _send_static(self, path: str, include_body: bool) -> None:
            name = static_name(path)
            if name is None:
                self._send_json(404, {"error": "not found"}, include_body)
                return
            root = app.static_dir.resolve()
            candidate = (root / name).resolve()
            if candidate.parent != root or not candidate.is_file():
                self._send_json(404, {"error": "not found"}, include_body)
                return
            self._send(200, candidate.read_bytes(), STATIC_TYPES[name], include_body)

        def _send_sermon(self, raw: str, include_body: bool) -> None:
            if not raw or "/" in raw or "\\" in raw or "%" in raw or ".." in raw:
                self._send_json(404, {"error": "not found"}, include_body)
                return
            meta = app.sermon(raw)
            if meta is None:
                self._send_json(404, {"error": "not found"}, include_body)
                return
            self._send_json(200, meta, include_body)

        def _respond(self, include_body: bool) -> None:
            try:
                self._route(include_body)
            except BadRequest as exc:
                if getattr(self, "_started", False):
                    self.close_connection = True
                    return
                self._send_json(exc.status, {"error": exc.message}, include_body)
            except Exception:
                logging.exception("request failed")
                if getattr(self, "_started", False):
                    self.close_connection = True
                    return
                self._send_json(500, {"error": "internal error"}, include_body)

        def do_GET(self) -> None:
            self._respond(True)

        def do_HEAD(self) -> None:
            self._respond(False)

        def _reject_method(self) -> None:
            try:
                self._limits_and_host()
            except BadRequest as exc:
                self._send_json(exc.status, {"error": exc.message}, True)
                return
            except Exception:
                logging.exception("request failed")
                self._send_json(500, {"error": "internal error"}, True)
                return
            body = json.dumps({"error": "method not allowed"}).encode("utf-8")
            self._started = True
            self.send_response(405)
            self._security_headers()
            self.send_header("Allow", "GET, HEAD")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            self._reject_method()

        def do_PUT(self) -> None:
            self._reject_method()

        def do_DELETE(self) -> None:
            self._reject_method()

        def do_PATCH(self) -> None:
            self._reject_method()

    return Handler


class PreachedServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def make_server(app: App, host: str, port: int) -> PreachedServer:
    return PreachedServer((host, port), make_handler(app))


def serve_forever(server: PreachedServer) -> None:
    host, port = server.server_address[:2]
    print(f"PREACHED_RSS_BYTES {rss_bytes() or 0}", flush=True)
    print(f"PREACHED_LISTENING http://{host}:{port}", flush=True)
    logging.info("listening on http://%s:%s", host, port)
    server.serve_forever()


def main(argv: list[str] | None = None) -> None:
    # Set before torch is imported. Queries are CPU; the GPU is Whisper's.
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Serve Preached search on this machine.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--library", default=LIBRARY, help="Classic library slug. Index defaults to /cache/index/<slug>.sqlite")
    parser.add_argument("--index", type=Path, default=None, help="SQLite index. Defaults to /cache/index/<library>.sqlite")
    parser.add_argument(
        "--church-library",
        default=None,
        help="Slug marked as your church. Default: the single index with meta role=church",
    )
    parser.add_argument(
        "--church-index",
        type=Path,
        default=None,
        help="SQLite file for your church. Overrides --church-library and the role mark",
    )
    parser.add_argument(
        "--hosts",
        default="127.0.0.1,localhost",
        help="Host header names to allow, comma-separated",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--bm25-only",
        action="store_true",
        help="Skip the embedding model and serve keyword search",
    )
    args = parser.parse_args(argv)
    if args.model not in MODELS:
        raise SystemExit(f"unknown model {args.model}")
    library = args.library.strip()
    if not LIBRARY_SLUG.fullmatch(library):
        raise SystemExit("library must be a short slug: lowercase letters, digits, and hyphens")
    church_library = args.church_library.strip() if args.church_library else None
    if church_library is not None and not LIBRARY_SLUG.fullmatch(church_library):
        raise SystemExit("church library must be a short slug: lowercase letters, digits, and hyphens")
    index = args.index if args.index is not None else INDEX_DIR / f"{library}.sqlite"
    if library == LIBRARY and args.index is None:
        index = INDEX_PATH
    church_path = resolve_church_path(
        INDEX_DIR,
        classic=index,
        church_index=args.church_index,
        church_library=church_library,
    )
    if church_path is None and (args.church_index is not None or church_library):
        logging.info("church library file is missing; that side will say nothing is there yet")
    elif args.church_index is None and not church_library:
        marks = church_index_matches(INDEX_DIR, exclude=index)
        if len(marks) > 1:
            logging.info(
                "more than one library is marked your church (%s); name one with --church-library",
                ", ".join(path.stem for path in marks),
            )
    church_slug = church_library
    if church_path is not None and church_slug is None:
        church_slug = church_path.stem if LIBRARY_SLUG.fullmatch(church_path.stem) else None
        if church_slug is None:
            logging.info("church index name %s is not a library slug; that side is empty", church_path.name)
            church_path = None
    try:
        connection = open_readonly(index, check_same_thread=False)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    church_connection = None
    try:
        if church_path is not None:
            try:
                church_connection = open_readonly(church_path, check_same_thread=False)
            except FileNotFoundError:
                logging.info("church library file is missing; that side will say nothing is there yet")
                church_connection = None
                church_slug = None
        hosts = {part.strip().lower() for part in args.hosts.split(",") if part.strip()}
        bound = args.host.strip().lower()
        if bound not in {"0.0.0.0", "::", ""}:
            hosts.add(bound)
        app = build_app(
            connection,
            model_key=args.model,
            bm25_only=args.bm25_only,
            hosts=hosts,
            static_dir=STATIC_DIR,
            library=library,
            church_connection=church_connection,
            church_library=church_slug if church_connection is not None else None,
        )
        if app.fallback_note:
            logging.warning("%s", app.fallback_note)
        elif app.encode is None:
            logging.info("BM25 only; the embedding model was not loaded")
        server = make_server(app, args.host, args.port)
        try:
            serve_forever(server)
        except KeyboardInterrupt:
            logging.info("stopping")
        finally:
            server.server_close()
    finally:
        connection.close()
        if church_connection is not None:
            church_connection.close()


if __name__ == "__main__":
    main()
