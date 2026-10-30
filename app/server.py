"""Search API and the mobile page.

Stdlib HTTP only. The embedding model loads once, on CPU. If it fails, search
falls back to BM25 and every search response says so. There are no write routes.

Security choices:
- static files are an allowlist, not a directory
- CSP has no inline script and no CDN
- the Host header must match the allowlist
- request target, header, and body size are limited; the socket times out
- clients never receive a traceback
- /healthz reports the index version and the model sha256, never a path
- each client IP has a request cap; X-Forwarded-For is ignored
- a kill file or PREACHED_DISABLED stops serving without a restart
- access logs keep the path and drop the query string
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from preached import env  # noqa: E402, F401
from preached.abstain import floor_for, search_with_confidence  # noqa: E402
from preached.backends import DEFAULT_EMBED_BACKEND  # noqa: E402
from preached.libraries import PUBLIC_DOMAIN, classic_index_problem, is_public_domain  # noqa: E402
from preached.models import DEFAULT_MODEL, MODELS  # noqa: E402
from preached.paths import INDEX_DIR, INDEX_PATH  # noqa: E402
from preached.search import (  # noqa: E402
    Searcher,
    display_excerpt,
    row_value,
    _optional_int,
    _text_or_none,
)
from preached.store import EmbeddingMismatch, check_query_variant, index_stamp, open_readonly  # noqa: E402
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
MAX_HEADER_BYTES = 8192
REQUEST_TIMEOUT_S = 15
# A shared test process issues well under this. serve.sh sets a tighter cap.
DEFAULT_RATE_LIMIT = 120
DEFAULT_RATE_WINDOW_S = 60.0
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
# Wesley ids are lowercase slugs (wesley-001), at most 64 characters. A
# YouTube video id is 11 characters and case-sensitive. Dots and slashes are
# not in either form, so a path cannot be an id.
SERMON_ID = re.compile(r"^(?:[a-z0-9][a-z0-9-]{0,63}|[A-Za-z0-9_-]{11})$")

FALLBACK_NOTE = "Embedding model failed to load; results are BM25 only."
BM25_ONLY_NOTE = "Embeddings are not loaded; results are BM25 only."
STALE_NOTE = "Stored passage vectors do not match the configured model; results are BM25 only."
INDEX_READ_NOTE = "The sermon index could not be checked; results are BM25 only."
REFUSED_ERROR = "index unavailable"

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


def public_sha256(value: object) -> str | None:
    """A lowercase sha256 hex string, or None. Anything else is dropped."""
    if isinstance(value, str) and SHA256_HEX.fullmatch(value):
        return value
    return None


def _positive_int(raw: str | None, default: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return value if value >= 1 else default


def _positive_float(raw: str | None, default: float) -> float:
    try:
        value = float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class RateLimiter:
    """Fixed window per key. The table is capped so a flood of IPs cannot grow it."""

    def __init__(self, limit: int, window_s: float, max_keys: int = 4096) -> None:
        self.limit = limit
        self.window_s = window_s
        self.max_keys = max_keys
        self.retry_after = max(1, int(window_s))
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= self.max_keys:
                    self._evict(moment)
                if key not in self._hits:
                    if len(self._hits) >= self.max_keys:
                        return False
                    hits = deque()
                    self._hits[key] = hits
                else:
                    hits = self._hits[key]
            cutoff = moment - self.window_s
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(moment)
            return True

    def _evict(self, now: float) -> None:
        cutoff = now - self.window_s
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]


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


def parse_search_args(args: dict, *, library: str = LIBRARY) -> tuple[str, int, str]:
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

    raw_library = _first(args, "library")
    chosen = library if raw_library is None or raw_library.strip() == "" else raw_library.strip()
    if chosen != library:
        raise BadRequest(f"library must be {library}")
    return query, k, mode


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


def default_loader(
    connection,
    model_key: str,
    embed_backend: str | None = None,
    ort_threads: int | None = None,
    variant: str | None = None,
):
    """Load the query embedder on CPU. The GPU stays with the Whisper job.

    The stored-vector fingerprint is checked before the weights load.
    ``embed_backend`` is ``onnx`` (the default) or ``torch``. Torch is
    imported only when that backend is selected.
    """
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    from preached.backends import load_embedder

    searcher = Searcher(connection, model=model_key)
    embedder = load_embedder(
        model_key,
        embed_backend,
        variant=variant,
        ort_threads=ort_threads,
        device="cpu",
        batch_size=1,
    )
    check_query_variant(connection, model_key, getattr(embedder, "variant", None))

    def encode(query: str):
        return embedder.encode_queries([query])[0]

    encode.backend = embedder.backend
    encode.variant = getattr(embedder, "variant", None)
    encode.threads = getattr(embedder, "threads", None)
    encode.model_sha256 = getattr(embedder, "model_sha256", None)
    return searcher, encode


def load_search(
    connection,
    model_key: str,
    *,
    bm25_only: bool = False,
    loader=None,
    embed_backend: str | None = None,
    ort_threads: int | None = None,
    variant: str | None = None,
):
    """Return (searcher, encode_or_none, fallback_note_or_none)."""
    if bm25_only:
        return Searcher(connection), None, None
    try:
        if loader is None:
            searcher, encode = default_loader(
                connection,
                model_key,
                embed_backend=embed_backend,
                ort_threads=ort_threads,
                variant=variant,
            )
        else:
            searcher, encode = loader(connection, model_key)
    except EmbeddingMismatch:
        # Never pair new query vectors with old document vectors.
        logging.exception("stored vectors do not match search/models.toml; serving BM25 only")
        return Searcher(connection), None, STALE_NOTE
    except Exception:
        logging.exception("embedding model unavailable; serving BM25 only")
        return Searcher(connection), None, FALLBACK_NOTE
    return searcher, encode, None


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
        backend=None,
        library: str = LIBRARY,
        rate_limit: int | None = None,
        rate_window_s: float | None = None,
        kill_file: Path | None = None,
        servable=None,
    ):
        """``servable(connection)`` raises SystemExit when the file may not be
        served (main passes ``check_servable``). It runs again before every
        searcher a reload builds; None skips it (tests)."""
        self.connection = connection
        self._servable = servable
        # Why the index is refused, or None. While set, nothing is served.
        self.refused = None
        self.searcher = searcher
        self._encode = encode
        self.encode = encode
        self._configured_model = model_name
        self._weights_ok = encode is not None
        self.fallback_note = fallback_note
        self.model_name = model_name if encode is not None else None
        self.backend = None if encode is None else (backend if backend is not None else getattr(encode, "backend", None))
        # Abstain floor for this embedder (search/abstain.toml). None: never
        # abstain on dense evidence. Dropped while a BM25 fallback is in
        # effect, and put back when a later reload finds the vectors again.
        self._floor = floor if encode is not None else None
        self.floor = self._floor
        self.hosts = frozenset(host.lower() for host in hosts)
        self.static_dir = Path(static_dir)
        self.lock = threading.Lock()
        self.library = library
        if rate_limit is None:
            rate_limit = _positive_int(os.environ.get("PREACHED_RATE_LIMIT"), DEFAULT_RATE_LIMIT)
        if rate_window_s is None:
            rate_window_s = _positive_float(
                os.environ.get("PREACHED_RATE_WINDOW_S"), DEFAULT_RATE_WINDOW_S
            )
        self.rate_limiter = RateLimiter(rate_limit, rate_window_s)
        self.kill_file = Path(kill_file) if kill_file else None
        self._stamp = self._capture_stamp()
        # A failed read must not let the next success adopt a stamp without
        # reloading. Init counts: the searcher was built before this read.
        self._status_failed = self._stamp is None

    def _capture_stamp(self):
        try:
            model = self._configured_model if self._weights_ok else None
            return index_stamp(self.connection, model)
        except Exception:
            logging.exception("could not read the index stamp")
            return None

    def _refuse_unless_servable(self) -> bool:
        """Re-run the serve gate on the open file. On failure drop every
        cached row and serve nothing (fail closed); True when refused."""
        if self._servable is None:
            self.refused = None
            return False
        try:
            self._servable(self.connection)
        except SystemExit as exc:
            problem = str(exc.code)
        except Exception as exc:
            problem = f"the index could not be checked ({exc})"
        else:
            self.refused = None
            return False
        logging.error("refusing to serve after reload: %s", problem)
        self.refused = problem
        self.searcher = None
        self.encode = None
        self.model_name = None
        self.backend = None
        self.floor = None
        return True

    def _serve_keyword_only(self, note: str) -> None:
        self.searcher = Searcher(self.connection)
        self.encode = None
        self.model_name = None
        self.backend = None
        self.floor = None
        self.fallback_note = note

    def _reload_cached_index(self) -> None:
        """Rebuild cached rows. fp32 pairing is checked again on this path."""
        if not self._weights_ok:
            self.searcher = Searcher(self.connection)
            return
        try:
            self.searcher = Searcher(self.connection, model=self._configured_model)
            check_query_variant(
                self.connection,
                self._configured_model,
                getattr(self._encode, "variant", None),
            )
        except (EmbeddingMismatch, RuntimeError):
            self._serve_keyword_only(STALE_NOTE)
            return
        self.encode = self._encode
        self.model_name = self._configured_model
        self.backend = getattr(self._encode, "backend", None)
        self.floor = self._floor
        self.fallback_note = None

    def _refresh_if_stale(self) -> None:
        """Reload cached rows and vectors when the chunk hash or embeddings changed.

        The searcher keeps both in memory from startup. A rebuild in the same
        file would otherwise keep serving the old text and deleted vectors
        until the process restarts. Missing or mismatched vectors fall back
        to BM25. The weights stay loaded so a later rebuild can use them.

        A failed status read drops this process to keyword search. The next
        successful read reloads, even when the stamp matches the last good
        one. It does not adopt the new stamp and keep the old rows.

        Every searcher built here is built only after ``servable`` passes on
        the open file. A refusal keeps ``_status_failed`` set, so the gate
        runs again on the next request.
        """
        stamp = self._capture_stamp()
        if stamp is None:
            self._status_failed = True
            if not self._refuse_unless_servable():
                self._serve_keyword_only(INDEX_READ_NOTE)
            return
        if not self._status_failed and stamp == self._stamp:
            return
        self._stamp = stamp
        if self._refuse_unless_servable():
            self._status_failed = True
            return
        self._status_failed = False
        self._reload_cached_index()

    def _check_refused(self) -> None:
        if self.refused is not None:
            raise BadRequest(REFUSED_ERROR, 503)

    def host_allowed(self, header_value: str) -> bool:
        return hostname_of(header_value) in self.hosts

    def disabled(self) -> bool:
        """True when the operator has thrown the kill switch.

        PREACHED_DISABLED is read on each call. A kill file is present or
        absent; its contents are never read and its path is never returned.
        """
        flag = os.environ.get("PREACHED_DISABLED", "").strip().lower()
        if flag in {"1", "true", "yes", "on"}:
            return True
        path = self.kill_file
        if path is None:
            raw = os.environ.get("PREACHED_KILL_FILE", "").strip()
            path = Path(raw) if raw else None
        if path is None:
            return False
        try:
            return path.is_file()
        except OSError:
            return False

    def _index_version(self) -> str | None:
        """chunks_sha256 from meta, if it is 64 hex chars. Not a path."""
        try:
            row = self.connection.execute(
                "SELECT value FROM meta WHERE key = 'chunks_sha256'"
            ).fetchone()
        except Exception:
            return None
        if row is None:
            return None
        return public_sha256(row[0])

    def health(self) -> dict:
        if self.disabled():
            return {"ok": False, "disabled": True}
        with self.lock:
            self._refresh_if_stale()
            self._check_refused()
            count = int(self.connection.execute("SELECT count(*) FROM chunks").fetchone()[0])
            index_version = self._index_version()
        model_sha = None
        if self.encode is not None:
            model_sha = public_sha256(getattr(self.encode, "model_sha256", None))
        return {
            "ok": True,
            "disabled": False,
            "library": self.library,
            "chunks": count,
            "model": self.model_name,
            "fallback": self.fallback_note is not None,
            "dense": self.encode is not None,
            "backend": self.backend,
            "abstain_calibrated": self.floor is not None,
            "index_version": index_version,
            "model_sha256": model_sha,
        }

    def search(self, query: str, k: int, mode: str) -> dict:
        started = time.perf_counter()
        note = None
        effective = mode
        with self.lock:
            self._refresh_if_stale()
            self._check_refused()
            if self.encode is None:
                if self.fallback_note:
                    note = self.fallback_note
                elif mode != "bm25":
                    note = BM25_ONLY_NOTE
                effective = "bm25"
            vector = None if effective == "bm25" else self.encode(query)
            kept, confidence = search_with_confidence(self.searcher, query, vector, effective, k, self.floor)
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

    def sermon(self, sermon_id: str) -> dict | None:
        if not SERMON_ID.fullmatch(sermon_id):
            return None
        with self.lock:
            self._refresh_if_stale()
            self._check_refused()
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
    embed_backend: str | None = None,
    ort_threads: int | None = None,
    variant: str | None = None,
    library: str = LIBRARY,
    rate_limit: int | None = None,
    rate_window_s: float | None = None,
    kill_file: Path | None = None,
    servable=None,
) -> App:
    """``floor`` overrides search/abstain.toml (tests); None reads the file."""
    searcher, encode, note = load_search(
        connection,
        model_key,
        bm25_only=bm25_only,
        loader=loader,
        embed_backend=embed_backend,
        ort_threads=ort_threads,
        variant=variant,
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
        rate_limit=rate_limit,
        rate_window_s=rate_window_s,
        kill_file=kill_file,
        servable=servable,
    )


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "Preached"
        sys_version = ""
        timeout = REQUEST_TIMEOUT_S

        def log_message(self, fmt, *args):
            # Drop anything after ? so a query is not written to the log.
            text = fmt % args if args else str(fmt)
            if "?" in text:
                text = text.split("?", 1)[0]
            logging.info("%s %s", self.client_address[0], text)

        def log_request(self, code="-", size="-"):
            path = (self.path or "/").split("?", 1)[0] or "/"
            status = getattr(code, "value", code)
            logging.info("%s %s %s %s", self.client_address[0], self.command, path, status)

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

        def _send(
            self,
            status: int,
            body: bytes,
            content_type: str,
            include_body: bool,
            extra_headers: dict | None = None,
        ) -> None:
            self._started = True
            self.send_response(status)
            self._security_headers()
            if extra_headers:
                for key, value in extra_headers.items():
                    self.send_header(key, value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if include_body:
                self.wfile.write(body)

        def _send_json(
            self,
            status: int,
            payload: dict,
            include_body: bool,
            extra_headers: dict | None = None,
        ) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(
                status,
                body,
                "application/json; charset=utf-8",
                include_body,
                extra_headers=extra_headers,
            )

        def _limits_and_host(self) -> None:
            try:
                header_bytes = len(self.headers.as_string().encode("latin-1", "replace"))
            except Exception as exc:
                raise BadRequest("request too large", 431) from exc
            if header_bytes > MAX_HEADER_BYTES:
                raise BadRequest("request too large", 431)
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

        def _limited_headers(self) -> dict:
            return {"Retry-After": str(app.rate_limiter.retry_after)}

        def _blocked(self, include_body: bool) -> str | None:
            """Size and host checks, then the kill switch, then the rate cap.

            Returns 'disabled' or 'limited' when the handler already replied.
            """
            self._limits_and_host()
            parsed = urlsplit(self.path)
            path = parsed.path or "/"
            if app.disabled():
                if path == "/healthz":
                    self._send_json(503, {"ok": False, "disabled": True}, include_body)
                else:
                    self._send_json(503, {"error": "unavailable"}, include_body)
                return "disabled"
            # The socket peer, never X-Forwarded-For. A proxy in front shares one bucket.
            if not app.rate_limiter.allow(self.client_address[0]):
                self._send_json(
                    429,
                    {"error": "too many requests"},
                    include_body,
                    extra_headers=self._limited_headers(),
                )
                return "limited"
            return None

        def _route(self, include_body: bool) -> None:
            if self._blocked(include_body):
                return
            parsed = urlsplit(self.path)
            path = parsed.path or "/"
            if path == "/":
                self._send_page(include_body)
                return
            if path == "/healthz":
                payload = app.health()
                self._send_json(200 if payload.get("ok") else 503, payload, include_body)
                return
            if path == "/api/search":
                try:
                    args = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=32)
                except ValueError as exc:
                    raise BadRequest("request too large", 414) from exc
                query, k, mode = parse_search_args(args, library=app.library)
                self._send_json(200, app.search(query, k, mode), include_body)
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
                extra = self._limited_headers() if exc.status == 429 else None
                self._send_json(exc.status, {"error": exc.message}, include_body, extra_headers=extra)
            except Exception as exc:
                # The exception text can quote the user's query. Log the type only.
                logging.error("request failed: %s", type(exc).__name__)
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
                if self._blocked(True):
                    return
            except BadRequest as exc:
                extra = self._limited_headers() if exc.status == 429 else None
                self._send_json(exc.status, {"error": exc.message}, True, extra_headers=extra)
                return
            except Exception as exc:
                logging.error("request failed: %s", type(exc).__name__)
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


# The Wesley index schema (store.connect), lower-cased: every table and view
# it may have, and every column each may have. Anything else (a church
# import's video_id, a review column, a side table) means it is not Wesley.
# Older indexes may lack the late columns, so a subset is fine.
WESLEY_SCHEMA = {
    "chunks": frozenset({
        "rowid", "chunk_id", "sermon_id", "sermon_title", "text", "start_s", "end_s", "sermon_number",
        "scripture", "source_url", "word_count", "word_start", "word_end", "librivox_id", "audio_url",
        "reader", "text_source",
    }),
    "chunks_fts": frozenset({"text", "sermon_title", "scripture"}),
    "chunks_fts_config": frozenset({"k", "v"}),
    "chunks_fts_data": frozenset({"id", "block"}),
    "chunks_fts_docsize": frozenset({"id", "sz"}),
    "chunks_fts_idx": frozenset({"segid", "term", "pgno"}),
    "embeddings": frozenset({"rowid", "model", "dim", "vector"}),
    "meta": frozenset({"key", "value"}),
}


def foreign_schema(connection) -> list[str]:
    """Tables, views and columns the Wesley index does not have, compared case-insensitively.

    SQLite's own ``sqlite_*`` tables (e.g. sqlite_stat1) are ignored.
    """
    foreign = []
    names = connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name")
    for (name,) in list(names):
        key = name.lower()
        if key.startswith("sqlite_"):
            continue
        allowed = WESLEY_SCHEMA.get(key)
        if allowed is None:
            foreign.append(name)
            continue
        quoted = name.replace('"', '""')
        for row in connection.execute(f'PRAGMA table_info("{quoted}")'):
            if row[1].lower() not in allowed:
                foreign.append(f"{name}.{row[1]}")
    return foreign


def file_identity(path: Path) -> tuple[int, int] | None:
    """(st_dev, st_ino) of ``path``, following symlinks; None when it cannot be read."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_dev, st.st_ino


def check_servable(connection, library: str, index: Path) -> None:
    """SystemExit unless this file is the Wesley index or an allow-listed public-domain library.

    Nothing else is served: church libraries (YouTube imports) have no
    redaction or approval gate yet, so they are refused (fail closed) until
    PR #12 lands.

    A classic (``--library spurgeon``/``edwards``) is served only from its
    canonical INDEX_DIR/<slug>.sqlite (``libraries.classic_index_problem``:
    realpath equality, no symlinks, owner and mode, one link), and that file
    must carry the matching
    ``library`` marker. A marker anywhere else is not trusted.

    Wesley must look like the Wesley index: chunks, every sermon id
    ``wesley-*``, no ``videos`` table, no ``library`` marker, and only the
    tables and columns in WESLEY_SCHEMA (case-insensitive), so no column a
    church import or the review gate adds, in chunks or a side table.
    """
    tables = {row[0].lower() for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    marker = None
    if "meta" in tables:
        row = connection.execute("SELECT value FROM meta WHERE key = 'library'").fetchone()
        marker = row[0] if row is not None else None
    allowed = f"allowed: {', '.join((LIBRARY, *PUBLIC_DOMAIN))}"
    if library != LIBRARY:
        problem = classic_index_problem(library, index, INDEX_DIR)
        if problem is not None:
            raise SystemExit(f"error: {problem}")
        if marker != library:
            raise SystemExit(f"error: {index} is not marked as the {library!r} library (marker {marker!r})")
        return
    if "videos" in tables or marker is not None:
        if marker is not None and is_public_domain(marker):
            raise SystemExit(f"error: {index} is the {marker!r} library; serve it with --library {marker}")
        raise SystemExit(
            f"error: {index} is not a public-domain library ({allowed}). Church libraries are not "
            "served until redaction and approval are in place."
        )
    foreign = foreign_schema(connection)
    if foreign:
        raise SystemExit(
            f"error: {index} has church-import columns or tables ({', '.join(foreign)}); "
            "it is not the Wesley index. "
            "Church libraries are not served until redaction and approval are in place."
        )
    wesley = "chunks" in tables and connection.execute(
        "SELECT count(*) > 0 AND count(*) = sum(sermon_id GLOB 'wesley-*') FROM chunks"
    ).fetchone()[0]
    if not wesley:
        raise SystemExit(f"error: {index} is not the Wesley index or a public-domain library ({allowed})")


def main(argv: list[str] | None = None) -> None:
    # Set before torch is imported. Queries are CPU; the GPU is Whisper's.
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Serve Preached search on this machine.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--library", default=LIBRARY, help="Library slug. Index defaults to /cache/index/<slug>.sqlite")
    parser.add_argument("--index", type=Path, default=None, help="SQLite index. Defaults to /cache/index/<library>.sqlite")
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
    parser.add_argument(
        "--embed-backend",
        choices=("onnx", "torch"),
        default=None,
        help=f"query embedder (default {DEFAULT_EMBED_BACKEND}, or PREACHED_EMBED_BACKEND)",
    )
    parser.add_argument("--onnx-variant", choices=("fp32",), default=None)
    parser.add_argument("--ort-threads", type=int, default=None, help="ONNX Runtime intra-op threads")
    args = parser.parse_args(argv)
    if args.model not in MODELS:
        raise SystemExit(f"unknown model {args.model}")
    library = args.library.strip()
    if not LIBRARY_SLUG.fullmatch(library):
        raise SystemExit("library must be a short slug: lowercase letters, digits, and hyphens")
    if library != LIBRARY and not is_public_domain(library):
        raise SystemExit(
            f"error: --library {library!r} refused: only {', '.join((LIBRARY, *PUBLIC_DOMAIN))} are served. "
            "Church libraries are not served until redaction and approval are in place."
        )
    index = args.index if args.index is not None else INDEX_DIR / f"{library}.sqlite"
    if library == LIBRARY and args.index is None:
        index = INDEX_PATH
    # The file checked must be the file opened: same (st_dev, st_ino) before
    # the open and after the checks, and again before every reload.
    identity = file_identity(index)
    try:
        connection = open_readonly(index, check_same_thread=False)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc

    def servable(conn) -> None:
        check_servable(conn, library, index)
        if identity is None or file_identity(index) != identity:
            raise SystemExit(f"error: {index} was replaced while it was being opened or served; refused")

    try:
        servable(connection)
    except sqlite3.DatabaseError as exc:
        connection.close()
        raise SystemExit(f"error: {index} is not a SQLite index ({exc})") from exc
    except BaseException:
        connection.close()
        raise
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
        embed_backend=args.embed_backend,
        ort_threads=args.ort_threads,
        variant=args.onnx_variant,
        library=library,
        servable=servable,
    )
    if app.fallback_note:
        logging.warning("%s", app.fallback_note)
    elif app.encode is None:
        logging.info("BM25 only; the embedding model was not loaded")
    else:
        logging.info("index opened read-only for library %s", library)
        logging.info(
            "embed backend=%s variant=%s threads=%s",
            getattr(app.encode, "backend", None),
            getattr(app.encode, "variant", None),
            getattr(app.encode, "threads", None),
        )
    server = make_server(app, args.host, args.port)
    try:
        serve_forever(server)
    except KeyboardInterrupt:
        logging.info("stopping")
    finally:
        server.server_close()
        connection.close()


if __name__ == "__main__":
    main()
