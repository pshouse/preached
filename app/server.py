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
from preached.models import DEFAULT_MODEL, MODELS  # noqa: E402
from preached.paths import INDEX_DIR, INDEX_PATH  # noqa: E402
from preached.search import (  # noqa: E402
    Searcher,
    display_excerpt,
    touches_flagged,
    row_value,
    _optional_int,
    _text_or_none,
)
from preached.audio_policy import public_times, resolve_flagged_audio  # noqa: E402
from preached.privacy import default_config  # noqa: E402
from preached.store import EmbeddingMismatch, open_readonly, pending_review_count, visible_count, visible_sql  # noqa: E402
from preached.youtube.listing import chunk_video_id, policy_watch_url, public_audio_url  # noqa: E402

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


def _youtube_like(url) -> bool:
    """Any string naming a YouTube host, valid or not (fail closed)."""
    return isinstance(url, str) and ("youtube" in url.lower() or "youtu.be" in url.lower())


def hit_dict(hit, flagged_audio: str = "none", near_flag: bool = False) -> dict:
    """The JSON for one result. A chunk with ``[name]`` or a review flag follows
    the flagged-audio policy: ``none`` drops the play link and both times,
    ``shifted`` starts after the flagged words (``start_s`` = ``play_from_s``,
    no ``end_s``), ``play`` is the normal link. See ``audio_policy.public_times``.
    ``near_flag`` (``search.touches_flagged``) withholds audio under ``none``
    for a card whose span touches a flagged chunk. A YouTube link on a flagged
    card is rebuilt from validated parts, and under ``none`` or ``shifted`` its
    YouTube source link (a watch link from 0:00) is dropped."""
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
    result = {key: payload[key] for key in RESULT_FIELDS}
    flag_end_s = getattr(hit, "flag_end_s", None)
    if flag_end_s is None:
        if not (near_flag and flagged_audio == "none"):
            return result
        # Unflagged, but its span touches a flagged chunk (search.touches_flagged):
        # under none a play link would run on into the name, so withhold it too.
        start_s, end_s, play_from, allowed = None, None, None, False
    else:
        start_s, end_s, play_from, allowed = public_times(hit.start_s, hit.end_s, flag_end_s, flagged_audio)
    result["start_s"] = start_s
    result["end_s"] = end_s
    youtube = _youtube_like(hit.audio_url) or _youtube_like(hit.source_url)
    if youtube and flagged_audio != "play":
        # A YouTube source link is a watch link from 0:00, which would play
        # the name; under none or shifted only the rebuilt link may remain.
        result["source_url"] = None
    if not allowed:
        result["audio_url"] = None
        result["audio_withheld"] = True
        return result
    vid = chunk_video_id(hit.video_id, hit.audio_url, hit.source_url)
    if vid is not None or youtube:
        # Rebuilt from validated parts, never the stored link: its t= was set
        # at import time and may sit on the name. Under shifted, t= is the
        # shifted start. A YouTube link that does not validate is withheld.
        result["audio_url"] = policy_watch_url(vid, hit.start_s, hit.end_s, hit.flag_end_s, flagged_audio)
        if result["audio_url"] is None:
            result["audio_withheld"] = True
            result["start_s"] = result["end_s"] = None
            result["source_url"] = None
            return result
    if play_from is not None:
        result["play_from_s"] = play_from
    return result


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


class App:
    def __init__(self, connection, searcher, encode, fallback_note, model_name, hosts, static_dir, floor=None, library: str = LIBRARY, flagged_audio: str | None = None):
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
        # Any library but wesley is gated. The gate is checked per request in
        # SQL (preached.store.visible_sql), so an import, --redo or approval
        # made while this process runs applies to the next request.
        self.gated = library != LIBRARY
        if hasattr(searcher, "gated"):
            searcher.gated = searcher.gated or self.gated
        self.flagged_audio = resolve_flagged_audio(flagged_audio, default_config().flagged_audio)

    def host_allowed(self, header_value: str) -> bool:
        return hostname_of(header_value) in self.hosts

    def health(self) -> dict:
        with self.lock:
            count = visible_count(self.connection, gated=self.gated)
            pending = pending_review_count(self.connection) if self.gated else None
        payload = {
            "ok": True,
            "library": self.library,
            "chunks": count,
            "model": self.model_name,
            "fallback": self.fallback_note is not None,
            "dense": self.encode is not None,
            "abstain_calibrated": self.floor is not None,
        }
        if pending is not None:
            # A count only: sermons imported but not approved. Never ids or titles.
            payload["pending_review"] = pending
        return payload

    def search(self, query: str, k: int, mode: str) -> dict:
        started = time.perf_counter()
        note = None
        effective = mode
        with self.lock:
            if self.encode is None:
                if self.fallback_note:
                    note = self.fallback_note
                elif mode != "bm25":
                    note = BM25_ONLY_NOTE
                effective = "bm25"
            vector = None if effective == "bm25" else self.encode(query)
            kept, confidence = search_with_confidence(self.searcher, query, vector, effective, k, self.floor)
            nears = [self.flagged_audio == "none" and touches_flagged(self.connection, hit) for hit in kept]
        return {
            "query": query,
            "mode": effective,
            "took_ms": int(round((time.perf_counter() - started) * 1000)),
            "results": [hit_dict(hit, self.flagged_audio, near) for hit, near in zip(kept, nears)],
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
            where = visible_sql(self.connection, "chunks", gated=self.gated)
            sql = "SELECT * FROM chunks WHERE sermon_id = ?" + (f" AND {where}" if where else "") + " ORDER BY rowid"
            rows = list(self.connection.execute(sql, (sermon_id,)))
        if not rows:
            return None
        first = rows[0]
        audio_url = None
        reader = None
        for row in rows:
            flagged = row_value(row, "flag_end_s") is not None
            if audio_url is None and not (flagged and self.flagged_audio != "play"):
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
    connection, *, model_key: str, bm25_only: bool, hosts, static_dir, loader=None, floor=None, library: str = LIBRARY,
    flagged_audio: str | None = None,
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
        flagged_audio=flagged_audio,
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
        "--flagged-audio",
        default=None,
        help="Play links for chunks with [name] or a review flag: play, shifted or none (default none). Also $PREACHED_FLAGGED_AUDIO or the privacy TOML key.",
    )
    args = parser.parse_args(argv)
    try:
        resolve_flagged_audio(args.flagged_audio, default_config().flagged_audio)
    except (ValueError, OSError) as exc:
        raise SystemExit(f"flagged audio policy: {exc}") from exc
    if args.model not in MODELS:
        raise SystemExit(f"unknown model {args.model}")
    library = args.library.strip()
    if not LIBRARY_SLUG.fullmatch(library):
        raise SystemExit("library must be a short slug: lowercase letters, digits, and hyphens")
    index = args.index if args.index is not None else INDEX_DIR / f"{library}.sqlite"
    if library == LIBRARY and args.index is None:
        index = INDEX_PATH
    try:
        connection = open_readonly(index, check_same_thread=False)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
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
        flagged_audio=args.flagged_audio,
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
        connection.close()


if __name__ == "__main__":
    main()
