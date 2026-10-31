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
- /healthz shares that cap; a full client table refuses new clients
- concurrent connections are capped globally and per client
- the whole header block has one deadline, not a timeout per read
- a regular kill file stops and resumes serving on the next request
- anything unexpected at the kill path is treated as killed
- access logs keep the path, drop the query string, and escape controls
- a group- or world-writable bundle is refused; modes are not repaired
- a 405, or any earlier error, that leaves a body unread closes the connection
- any Transfer-Encoding, or a repeated or non-digit Content-Length, is refused
  and the connection closed
- from a bundle (build stamp PREACHED_BUNDLE), MANIFEST.sha256 must parse,
  list the stamp and match, no bytecode may sit in the tree, and the index
  and model/ must be the bundle's own, or the server does not start
  (app/bundle.py). A tree that is neither a bundle nor a .git checkout is
  refused
- scripts/serve.sh runs that check, stdlib only, before any bundle code is
  imported. Started directly (python app/server.py, python -B, uv run), no
  bytecode is read or written: the first lines below set a private
  sys.pycache_prefix before app.bundle and preached.* are imported. Those
  modules still run from their .py files before main() checks them, so an
  edited .py or a planted extension module runs first. python -m app.server
  is not covered (docs/DEPLOY.md)
- a bundle's index is frozen: a change after start is 503 until restart
- a NUL or control character in the request line or a header value is a 400
- SIGTERM drains the handler threads before the index and the ONNX session
  close (serve_until_stopped); nothing is served after a SIGTERM
"""

from __future__ import annotations

import atexit
import shutil
import signal
import sys
import tempfile

# Before any app or preached import. ``python app/server.py``, ``python -B``
# and ``uv run`` import app.bundle and preached.* below, before main() runs
# bundle_problem. An old __pycache__ in the tree can match a source file's
# size and mtime and would run in place of that source. A fresh, private,
# empty prefix means every one of those modules is compiled from source,
# and nothing is written. Removed at exit. Run as a script, SIGTERM is a
# requested stop from here on; it is blocked from before the directory
# exists until the atexit hook and handler are in place, so no SIGTERM can
# leak it. An importer (tests, scripts) gets the directory and atexit hook
# but no signal handler.
#
# Before serving, the handler raises SystemExit(0). It also records the
# request, because an import can swallow that exception (onnxruntime turns
# it into ImportError and the server would fall back to BM25); main checks
# the record before it serves. While serving, the handler raises nothing: it
# asks the serve loop to stop from another thread, so the accept thread is
# never interrupted half way through starting a handler thread, and main
# drains the handlers before it closes the index (serve_until_stopped).
sys.dont_write_bytecode = True
_SCRIPT = __name__ == "__main__"
_STOP: dict = {"requested": False, "server": None, "stopping": False}


def _on_stop_signal(_signum, _frame) -> None:
    _STOP["requested"] = True
    server = _STOP["server"]
    if server is None:
        sys.exit(0)
    if _STOP["stopping"]:
        return
    _STOP["stopping"] = True
    import threading

    try:
        threading.Thread(target=server.shutdown, name="preached-stop", daemon=True).start()
    except RuntimeError:  # interpreter already shutting down
        pass


if _SCRIPT and hasattr(signal, "pthread_sigmask"):
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
try:
    sys.pycache_prefix = tempfile.mkdtemp(prefix="preached-pycache-")
    atexit.register(shutil.rmtree, sys.pycache_prefix, ignore_errors=True)
    if _SCRIPT:
        signal.signal(signal.SIGTERM, _on_stop_signal)
finally:
    # Also when mkdtemp fails: SIGTERM must not stay blocked.
    if _SCRIPT and hasattr(signal, "pthread_sigmask"):
        signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM})

import argparse  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import socket  # noqa: E402
import sqlite3  # noqa: E402
import stat  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from collections import deque  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
from pathlib import Path  # noqa: E402
from urllib.parse import parse_qs, urlsplit  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
# ``uv run app/server.py`` puts app/ on the path, not the root.
if str(ROOT) not in sys.path:
    sys.path.insert(1, str(ROOT))

from app.bundle import (  # noqa: E402, F401
    BUILD_STAMP,
    BUNDLE_MARKERS,
    ONNX_ROOT_ENV,
    bundle_problem,
    is_bundle,
    onnx_dir_problem,
)
from preached import env  # noqa: E402, F401
from preached.abstain import floor_for, search_with_confidence  # noqa: E402
from preached.backends import DEFAULT_EMBED_BACKEND  # noqa: E402
from preached.libraries import PUBLIC_DOMAIN, classic_index_problem, is_public_domain  # noqa: E402
from preached.library import (  # noqa: E402
    CHURCH_EMPTY,
    CHURCH_LABEL,
    CLASSIC_LABEL,
    classic_church_refusal,
    read_label,
)
from preached.models import DEFAULT_MODEL, MODELS, RUNTIME_MODELS  # noqa: E402
from preached.paths import INDEX_DIR, INDEX_PATH  # noqa: E402
from preached.search import (  # noqa: E402
    Searcher,
    display_excerpt,
    play_start,
    sermon_flagged,
    touches_flagged,
    row_value,
    _optional_int,
    _text_or_none,
)
from preached.audio_policy import public_times, resolve_flagged_audio  # noqa: E402
from preached.privacy import MissingConfig, default_config, required_config  # noqa: E402
from preached.store import (  # noqa: E402
    EmbeddingMismatch,
    UnsafeSidecar,
    check_query_variant,
    index_stamp,
    open_readonly,
    pending_review_count,
    public_domain_file,
    visible_count,
    visible_sql,
)
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
# RFC 9110 token, and a Content-Length of digits with optional SP/HTAB around.
HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
CONTENT_LENGTH = re.compile(r"[ \t]*[0-9]{1,10}[ \t]*")
MAX_HEADER_BYTES = 8192
# RFC 9110 5.5: a field value is visible characters, SP and HTAB. NUL, CR,
# LF and every other control character are refused. The request line may
# carry none at all, apart from its CRLF ending.
HEADER_VALUE_BAD = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")
REQUEST_LINE_BAD = re.compile(rb"[\x00-\x1f\x7f]")
REQUEST_TIMEOUT_S = 15
# One deadline for the request line and all headers together. A per-read
# timeout let a client drip one header line at a time and hold a thread.
HEADER_DEADLINE_S = 15.0
# On stop, how long main waits for handler threads before it gives up
# without closing the index (PreachedServer.drain).
DRAIN_TIMEOUT_S = 10.0
# Thread per connection. These caps are the backstop for that.
DEFAULT_MAX_CONNECTIONS = 32
DEFAULT_MAX_CLIENT_CONNECTIONS = 4
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


def escape_controls(value: object) -> str:
    """ASCII, with control characters written as ``\\xHH``.

    A request line must not be able to inject a second log line or a
    terminal escape. The query string is removed by the caller first.
    """
    text = "" if value is None else str(value)
    parts: list[str] = []
    for char in text:
        code = ord(char)
        if code < 32 or code == 127:
            parts.append("\\x%02x" % code)
        elif char == "\\":
            parts.append("\\\\")
        else:
            parts.append(char)
    return "".join(parts)


def kill_file_engaged(path: Path) -> bool:
    """True when the kill switch is on, or the path is not a normal absence.

    A missing file in a readable directory is off, so removing a regular
    kill file resumes serving on the next request. A directory, a symlink
    (dangling or not), an unreadable parent, or any other surprise is on.
    The file's contents are never read.
    """
    try:
        os.lstat(path)
    except FileNotFoundError:
        return _kill_parent_unexpected(path)
    except OSError:
        return True
    return True


def _kill_parent_unexpected(path: Path) -> bool:
    """True when the missing kill file's parent is not a normal directory."""
    current = path.parent
    while True:
        try:
            listed = os.lstat(current)
        except FileNotFoundError:
            if current == current.parent:
                return False
            current = current.parent
            continue
        except OSError:
            return True
        if stat.S_ISLNK(listed.st_mode):
            try:
                followed = os.stat(current)
            except OSError:
                return True
            if not stat.S_ISDIR(followed.st_mode):
                return True
            return False
        if not stat.S_ISDIR(listed.st_mode):
            return True
        return False


class RateLimiter:
    """Fixed window per client key.

    The table holds at most ``max_keys`` keys. Keys with no hit in the
    current window are dropped before a new key is added. When the table
    is still full, a new key is refused and an existing key is left alone.
    That is fail closed: an unknown client gets no service until some key
    goes idle. ``/healthz`` uses this same window. It is not exempt and it
    does not have its own bucket.
    """

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


def _youtube_like(url) -> bool:
    """Any string naming a YouTube host, valid or not (fail closed)."""
    return isinstance(url, str) and ("youtube" in url.lower() or "youtu.be" in url.lower())


def timed_link(hit) -> str | None:
    """This passage's own seeked link, or None when it would be untimed (play from 0:00).

    A YouTube link is rebuilt by ``policy_watch_url`` and must carry ``t=``.
    Any other URL must pass ``public_audio_url`` and the passage must have a
    start the page can seek to (``play_start``).
    """
    if _youtube_like(hit.audio_url) or _youtube_like(hit.source_url):
        vid = chunk_video_id(getattr(hit, "video_id", None), hit.audio_url, hit.source_url)
        url = policy_watch_url(vid, hit.start_s, hit.end_s, None, "none")
        return url if url is not None and "&t=" in url else None
    url = public_audio_url(hit.audio_url)
    return url if url is not None and play_start(hit.start_s) is not None else None


def hit_dict(hit, flagged_audio: str = "none", near_flag: bool = False, sermon_flagged: bool = False) -> dict:
    """The JSON for one result. A chunk with ``[name]`` or a review flag follows
    the flagged-audio policy: ``none`` drops the play link and both times,
    ``play`` is the normal link. See ``audio_policy.public_times``.
    ``near_flag`` (``search.touches_flagged``) withholds audio under ``none``
    for a card whose span touches a flagged chunk. A YouTube link on a flagged
    card is rebuilt from validated parts, and under ``none`` its
    YouTube source link (a watch link from 0:00) is dropped.

    ``sermon_flagged`` (``search.sermon_flagged``): Patrick's link rule. In a
    sermon with any flagged passage, an unflagged card keeps only its own
    timed link (``timed_link``); its ``source_url`` and any untimed link are
    dropped, since they play from 0:00."""
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
            if sermon_flagged and flagged_audio != "play":
                result["source_url"] = None
                result["audio_url"] = timed_link(hit)
                if result["audio_url"] is None:
                    result["audio_withheld"] = True
            return result
        # Unflagged, but its span touches a flagged chunk (search.touches_flagged):
        # under none a play link would run on into the name, so withhold it too.
        start_s, end_s, allowed = None, None, False
    else:
        start_s, end_s, allowed = public_times(hit.start_s, hit.end_s, flag_end_s, flagged_audio)
    result["start_s"] = start_s
    result["end_s"] = end_s
    youtube = _youtube_like(hit.audio_url) or _youtube_like(hit.source_url)
    if flagged_audio != "play":
        # This sermon has a flagged passage: its source link (a YouTube watch
        # link or an archive.org page) plays from 0:00, which would reach the
        # name; under none only the rebuilt link may remain.
        result["source_url"] = None
    if not allowed:
        result["audio_url"] = None
        result["audio_withheld"] = True
        return result
    vid = chunk_video_id(hit.video_id, hit.audio_url, hit.source_url)
    if vid is not None or youtube:
        # Rebuilt from validated parts, never the stored link: its t= was set
        # at import time and may sit on the name. A YouTube link that does not validate is withheld.
        result["audio_url"] = policy_watch_url(vid, hit.start_s, hit.end_s, hit.flag_end_s, flagged_audio)
        if result["audio_url"] is None:
            result["audio_withheld"] = True
            result["start_s"] = result["end_s"] = None
            result["source_url"] = None
            return result
    return result


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
    encode.close = getattr(embedder, "close", None)
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


def load_church_searcher(connection, model_key: str, *, bm25_only: bool):
    """Searcher for the church file, plus a note when that side is BM25 only.

    Always built through #12's publish gate (``gated=True``, no slug, so the
    public-domain exemption never applies): only approved sermons are
    visible, checked per call. A bad or missing church vector file does not
    take the classic side down with it. The church column falls back to
    keyword search and says so.
    """
    gate = {"gated": True, "library": None}
    if bm25_only:
        return Searcher(connection, **gate), None
    try:
        return Searcher(connection, model=model_key, **gate), None
    except EmbeddingMismatch:
        logging.exception("church vectors do not match search/models.toml; that side is BM25 only")
        return Searcher(connection, **gate), STALE_NOTE
    except Exception:
        logging.exception("church vectors unavailable; that side is BM25 only")
        return Searcher(connection, **gate), STALE_NOTE


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
        church_connection=None,
        church_searcher=None,
        church_library: str | None = None,
        church_label: str | None = None,
        church_sample: bool | None = None,
        church_note: str | None = None,
        classic_label: str | None = None,
        frozen: bool = False,
    ):
        """``servable(connection)`` raises SystemExit when the file may not be
        served (main passes ``check_servable``). It runs again before every
        searcher a reload builds; None skips it (tests).

        ``frozen`` (main sets it when serving from a bundle): the index was
        hashed at start, so any change after start is refused with 503 until
        the process restarts. It is never reloaded."""
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
        self.classic_label = classic_label or read_label(connection) or (
            CLASSIC_LABEL if library == LIBRARY else library
        )
        # The church file is not served until PR #12's publish gate is on main.
        # Arguments are accepted so a caller can still pass the connection it
        # opened; they are not stored, so /healthz "church" stays null and
        # /api/side matches the no-church response (no present:true flag).
        # TODO(post-#12): keep the searcher once #12 is on main. It must use
        # #12's gate and per-request visible_sql, withhold audio on flagged
        # passages, apply the source_url rule to hits, and reload with #10's
        # index stamp. A church file passed as --library is refused by
        # check_servable (libraries.classic_index_problem for spurgeon and
        # edwards). Do not add a second serve check. Church confidence stays
        # unrated (abstain.church_confidence) until a floor is fitted on a
        # church library.
        del church_connection, church_searcher, church_library, church_label, church_sample, church_note
        self.church_connection = None
        self.church_searcher = None
        self.church_library = None
        self.church_label = CHURCH_LABEL
        self.church_sample = False
        self.church_note = None
        # Any library but wesley is gated, except an allow-listed public-domain
        # library's own file (store.public_domain_file, keyed on the slug).
        # The gate is checked per request in SQL (preached.store.visible_sql),
        # so an import, --redo or approval made while this process runs
        # applies to the next request.
        self.gated = library != LIBRARY
        if self.gated and hasattr(searcher, "gate_on"):
            searcher.gate_on()
        if hasattr(searcher, "library"):
            searcher.library = library
        if is_public_domain(library) and not public_domain_file(connection, library):
            logging.warning("%s is on the public-domain list but this file is not its own build; gate stays on", library)
        # Always "none" for church libraries (Patrick's decision). Tests may set
        # the attribute to exercise the other values; no flag, env or TOML can.
        self.flagged_audio = resolve_flagged_audio(default_config().flagged_audio)
        self.frozen = frozen
        # Set once in a frozen App when the index changed; never cleared.
        self._frozen_refusal = None
        self._data_version = self._read_data_version() if frozen else None
        self._stamp = self._capture_stamp()
        # A failed read must not let the next success adopt a stamp without
        # reloading. Init counts: the searcher was built before this read.
        self._status_failed = self._stamp is None

    def _read_data_version(self):
        try:
            return self.connection.execute("PRAGMA data_version").fetchone()[0]
        except Exception:
            logging.exception("could not read the index data_version")
            return None

    def _capture_stamp(self):
        try:
            model = self._configured_model if self._weights_ok else None
            return index_stamp(self.connection, model)
        except Exception:
            logging.exception("could not read the index stamp")
            return None

    def _searcher(self, model: str | None = None) -> Searcher:
        """Every searcher this App builds carries the gate and the slug (#12 x #10).

        The gate itself is still evaluated per request in SQL
        (``store.visible_sql``) and the Searcher still reloads vectors on
        ``PRAGMA data_version``; a reload only swaps the cached rows/vectors.
        """
        return Searcher(self.connection, model=model, gated=self.gated, library=self.library)
    def _refuse_unless_servable(self) -> bool:
        """Re-run the serve gate on the open file. On failure drop every
        cached row and serve nothing (fail closed); True when refused."""
        if self._frozen_refusal is not None:
            self.refused = self._frozen_refusal
            return True
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
        self._drop(problem)
        return True

    def _drop(self, problem: str) -> None:
        self.refused = problem
        self.searcher = None
        self.encode = None
        self.model_name = None
        self.backend = None
        self.floor = None

    def _serve_keyword_only(self, note: str) -> None:
        self.searcher = self._searcher()
        self.encode = None
        self.model_name = None
        self.backend = None
        self.floor = None
        self.fallback_note = note

    def close_embedder(self) -> None:
        """Release the query embedder (the ONNX session). Only after every
        handler thread has stopped: nothing may be inside it."""
        encode = self._encode
        self._encode = None
        self.encode = None
        close = getattr(encode, "close", None)
        if callable(close):
            close()

    def _reload_cached_index(self) -> None:
        """Rebuild cached rows. fp32 pairing is checked again on this path."""
        if not self._weights_ok:
            self.searcher = self._searcher()
            return
        try:
            self.searcher = self._searcher(self._configured_model)
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
        if self._frozen_refusal is not None:
            self.refused = self._frozen_refusal
            return
        stamp = self._capture_stamp()
        if self.frozen and (
            stamp is None or stamp != self._stamp or self._read_data_version() != self._data_version
        ):
            # A bundle's index was hashed at start. Any change, or a status
            # read that fails, is refused until restart; it is not reloaded.
            self._frozen_refusal = "the bundled index changed after start; restart the server"
            logging.error("refusing to serve: %s", self._frozen_refusal)
            self._drop(self._frozen_refusal)
            return
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

        Called on every request, so a regular kill file starts and stops
        serving without a process restart. ``PREACHED_DISABLED`` is read
        from this process's environment on each call. Another shell cannot
        change that environment; set the variable before start. The kill
        file is the switch that works without a restart.

        A regular file at the kill path is on. A missing file in a readable
        directory is off. A directory, a symlink, an unreadable parent, or
        any other surprise is on (fail closed). Contents and the path are
        never returned to the client.
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
        return kill_file_engaged(path)

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
            # /healthz re-runs the serve gate itself: a swapped -wal can leave the
            # stamp unchanged, so the reload above never looks. Refused means 503.
            if self.refused is None and self._refuse_unless_servable():
                self._status_failed = True
            self._check_refused()
            count = visible_count(self.connection, gated=self.gated, library=self.library)
            gated = self.gated and not public_domain_file(self.connection, self.library)
            pending = pending_review_count(self.connection) if gated else None
            index_version = self._index_version()
        model_sha = None
        if self.encode is not None:
            model_sha = public_sha256(getattr(self.encode, "model_sha256", None))
        payload = {
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
            "church": self.church_library,
        }
        if pending is not None:
            # A count only: sermons imported but not approved. Never ids or titles.
            payload["pending_review"] = pending
        return payload

    def library_names(self) -> list[str]:
        """Slugs this process will search. Classic first, then the church file."""
        names = [self.library]
        if self.church_library and self.church_library not in names:
            names.append(self.church_library)
        return names

    def search(self, query: str, k: int, mode: str, *, library: str | None = None) -> dict:
        """Search the classic library. A church slug is not open.

        Until PR #12's gate is on main, a church library is refused the same
        way as any slug this process did not open. There is no church searcher
        to consult, so the response matches a server started with no church file.
        """
        chosen = self.library if library is None else library
        if chosen != self.library:
            raise BadRequest("library must be " + " or ".join(self.library_names()))
        started = time.perf_counter()
        note = None
        effective = mode
        with self.lock:
            self._refresh_if_stale()
            self._check_refused()
            searcher = self.searcher
            # No query encoder, or this file has no usable vectors: keyword
            # search, same rule as a BM25-only process.
            if self.encode is None or searcher._matrix is None:
                if self.encode is None and self.fallback_note:
                    note = self.fallback_note
                elif mode != "bm25":
                    note = BM25_ONLY_NOTE
                effective = "bm25"
            vector = None if effective == "bm25" else self.encode(query)
            kept, confidence = search_with_confidence(searcher, query, vector, effective, k, self.floor)
            nears = [self.flagged_audio == "none" and touches_flagged(self.connection, hit) for hit in kept]
            flagged = {sid: sermon_flagged(self.connection, sid) for sid in {hit.sermon_id for hit in kept}}
        return {
            "query": query,
            "mode": effective,
            "took_ms": int(round((time.perf_counter() - started) * 1000)),
            "results": [
                hit_dict(hit, self.flagged_audio, near, flagged[hit.sermon_id]) for hit, near in zip(kept, nears)
            ],
            "note": note,
            # True when the page should say nothing strong was found. The
            # closest passages stay in results so a person can still look.
            "abstain": confidence.abstain,
            "confidence": confidence.as_dict(),
        }

    def side(self, query: str, k: int, mode: str) -> dict:
        """Top ``k`` hits from the classic library, and an empty church side.

        The church column is the same object a process with no church file
        returns. Church passages are not searched until PR #12's gate is on
        main, so this response has no church hit, no timed watch link, and
        no ``present: true`` flag.
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
            self._refresh_if_stale()
            self._check_refused()
            where = visible_sql(self.connection, "chunks", gated=self.gated, library=self.library)
            sql = "SELECT * FROM chunks WHERE sermon_id = ?" + (f" AND {where}" if where else "") + " ORDER BY rowid"
            rows = list(self.connection.execute(sql, (sermon_id,)))
            if not rows:
                return None
            audio_url, source_url = self._sermon_links(rows)
        first = rows[0]
        reader = None
        for row in rows:
            reader = _text_or_none(row_value(row, "reader"))
            if reader:
                break
        return {
            "sermon_id": sermon_id,
            "sermon_number": _optional_int(row_value(first, "sermon_number")),
            "sermon_title": first["sermon_title"],
            "scripture": _text_or_none(row_value(first, "scripture")),
            "source_url": source_url,
            "audio_url": audio_url,
            "reader": reader,
        }

    def _sermon_links(self, rows) -> tuple[str | None, str | None]:
        """``(audio_url, source_url)`` for /api/sermon, under the same rules as a card.

        The stored ``audio_url`` is never passed through: it goes through
        ``public_audio_url``, and a YouTube link is rebuilt by
        ``policy_watch_url`` (the stored ``t=`` was set at import time and may
        sit on a name).

        Patrick's link rule, when any chunk of the sermon is flagged (unless
        the policy is ``play``): ``source_url`` is dropped, flagged chunks
        and (under ``none``) chunks that touch one (``touches_flagged``) give
        no link, and ``audio_url`` is the first remaining chunk's own timed
        link (``timed_link``: a YouTube ``t=``, or ``#t=<seek>`` on an audio
        file), never an untimed link that plays from 0:00. If no chunk has
        one there is no link. A sermon with no flagged chunk is unchanged:
        the first chunk's link and its ``source_url``.
        """
        policy = self.flagged_audio
        flagged_any = policy != "play" and any(row_value(row, "flag_end_s") is not None for row in rows)
        source_url = None if flagged_any else _text_or_none(row_value(rows[0], "source_url"))
        for row in rows:
            card = SimpleNamespace(
                sermon_id=row["sermon_id"],
                flag_end_s=row_value(row, "flag_end_s"),
                word_start=row_value(row, "word_start"),
                word_end=row_value(row, "word_end"),
                start_s=row_value(row, "start_s"),
                end_s=row_value(row, "end_s"),
                video_id=row_value(row, "video_id"),
                audio_url=_text_or_none(row_value(row, "audio_url")),
                source_url=_text_or_none(row_value(row, "source_url")),
            )
            if card.audio_url is None:
                continue
            if flagged_any:
                if card.flag_end_s is not None:
                    continue
                if policy == "none" and touches_flagged(self.connection, card):
                    continue
                url = timed_link(card)
                if url is not None and not _youtube_like(url):
                    url = f"{url.split('#')[0]}#t={play_start(card.start_s):g}"
            elif _youtube_like(card.audio_url) or _youtube_like(card.source_url):
                vid = chunk_video_id(card.video_id, card.audio_url, card.source_url)
                url = policy_watch_url(vid, card.start_s, card.end_s, card.flag_end_s, policy)
            else:
                url = public_audio_url(card.audio_url)
            if url is not None:
                return url, source_url
        return None, source_url


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
    church_connection=None,
    church_library: str | None = None,
    church_label: str | None = None,
    church_sample: bool | None = None,
    frozen: bool = False,
) -> App:
    """``floor`` overrides search/abstain.toml (tests); None reads the file."""
    if model_key not in RUNTIME_MODELS:
        # Same refusal as main(); never fall back to keyword search quietly,
        # whether the key is eval-only or a typo.
        reason = "eval-only, not available to the server" if model_key in MODELS else "unknown model"
        raise ValueError(f"model {model_key}: {reason}")
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
    # church_* are accepted so existing callers still type-check. They are
    # not opened into a searcher. Serving waits on PR #12. See App.__init__.
    del church_connection, church_library, church_label, church_sample
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
        frozen=frozen,
    )


class _HeaderDeadlineSocket:
    """Apply one deadline to every header read.

    ``socket.recv`` is read-only, so the timeout cannot be patched onto the
    socket. ``makefile`` also buffers: one ``readline`` calls ``recv_into``
    many times, and each of those calls gets a fresh socket timeout. A
    client that drips one byte per read never trips a per-read timeout.
    This wrapper sits in ``SocketIO._sock`` and re-arms the remaining budget
    before every read.
    """

    def __init__(self, sock, deadline: float) -> None:
        self._sock = sock
        self._deadline = deadline

    def _arm(self) -> None:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("header deadline exceeded")
        self._sock.settimeout(remaining)

    def recv(self, n, flags=0):
        self._arm()
        return self._sock.recv(n, flags)

    def recv_into(self, buf, nbytes=0, flags=0):
        self._arm()
        return self._sock.recv_into(buf, nbytes, flags)


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "Preached"
        sys_version = ""
        timeout = REQUEST_TIMEOUT_S

        def _header_deadline_s(self) -> float:
            server = getattr(self, "server", None)
            raw = getattr(server, "header_deadline_s", HEADER_DEADLINE_S)
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return HEADER_DEADLINE_S
            return value if value > 0 else HEADER_DEADLINE_S

        def _install_header_deadline(self, deadline: float):
            """Return the SocketIO to restore, or None when there is nothing to wrap."""
            raw = getattr(self.rfile, "raw", None)
            sock = getattr(raw, "_sock", None) if raw is not None else None
            if raw is None or sock is None or isinstance(sock, _HeaderDeadlineSocket):
                try:
                    self.connection.settimeout(self._header_deadline_s())
                except OSError:
                    pass
                return None
            raw._sock = _HeaderDeadlineSocket(sock, deadline)
            return raw

        def _framing_problem(self) -> int | None:
            """Status to refuse a request whose body framing is not plain, or None.

            No route reads a body, so the only framing this server accepts is
            none, or exactly one Content-Length of ASCII digits. Anything a
            proxy might frame differently is refused and the connection is
            closed: any Transfer-Encoding (even empty), a repeated
            Content-Length, a sign, a comma list, or a header name that is
            not a token (``Content-Length :``).
            """
            headers = getattr(self, "headers", None)
            if headers is None:
                return None
            # A line the header parser could not take ("Content-Length : 5")
            # ends the headers early and lands in the payload. Refuse it, and
            # refuse obs-fold continuation lines, rather than guess.
            if getattr(headers, "defects", None) or headers.get_payload():
                return 400
            for name, value in headers.items():
                if not HEADER_NAME.fullmatch(name) or HEADER_VALUE_BAD.search(value):
                    return 400
            if headers.get_all("Transfer-Encoding"):
                return 501
            lengths = headers.get_all("Content-Length") or []
            if len(lengths) > 1:
                return 400
            if lengths and not CONTENT_LENGTH.fullmatch(lengths[0]):
                return 400
            return None

        def _has_unread_body(self) -> bool:
            """True when the client declared a body this server did not read.

            No route reads a body. Leaving those bytes on a keep-alive
            connection makes the next ``handle_one_request`` parse them as a
            second request (a POST body smuggled after a 405, or after any
            earlier error). Framing that is not one plain zero
            Content-Length counts as a body.
            """
            headers = getattr(self, "headers", None)
            if headers is None:
                return False
            if self._framing_problem() is not None:
                return True
            lengths = headers.get_all("Content-Length") or []
            if not lengths:
                return False
            return int(lengths[0]) != 0

        def _close_if_unread_body(self) -> None:
            if self._has_unread_body():
                self.close_connection = True

        def handle_one_request(self) -> None:
            # Headers share one deadline. The handler then runs under the
            # normal socket timeout, so a search is not cut off by the
            # header budget.
            deadline = time.monotonic() + self._header_deadline_s()
            raw = None
            parsed = False
            try:
                raw = self._install_header_deadline(deadline)
                self.raw_requestline = self.rfile.readline(65537)
                if len(self.raw_requestline) > 65536:
                    self.requestline = ""
                    self.request_version = ""
                    self.command = ""
                    self.send_error(414)
                    return
                if not self.raw_requestline:
                    self.close_connection = True
                    return
                line = self.raw_requestline
                line = line[:-2] if line.endswith(b"\r\n") else line.rstrip(b"\n")
                if REQUEST_LINE_BAD.search(line):
                    # Never echoed or logged: the line is the attacker's bytes.
                    self.requestline = ""
                    self.request_version = ""
                    self.command = ""
                    self.close_connection = True
                    self.send_error(400)
                    return
                if not self.parse_request():
                    return
                parsed = True
            except TimeoutError:
                self.close_connection = True
                logging.error("request failed: %s", "TimeoutError")
                return
            except Exception as exc:
                # A bad request line must not escape the thread. The type is
                # enough; the line itself can carry control characters.
                logging.error("request failed: %s", type(exc).__name__)
                self.close_connection = True
                return
            finally:
                if raw is not None:
                    wrapped = getattr(raw, "_sock", None)
                    if isinstance(wrapped, _HeaderDeadlineSocket):
                        raw._sock = wrapped._sock
                try:
                    self.connection.settimeout(REQUEST_TIMEOUT_S)
                except OSError:
                    pass
            if not parsed:
                return
            # Refuse ambiguous body framing before any route runs. The
            # connection closes, so bytes after the headers are never parsed
            # as a second request.
            framing = self._framing_problem()
            if framing is not None:
                self.close_connection = True
                self.send_error(framing)
                return
            try:
                method_name = "do_" + str(self.command)
                if not hasattr(self, method_name):
                    self.send_error(501)
                    return
                getattr(self, method_name)()
                self.wfile.flush()
            except TimeoutError:
                self.close_connection = True
                logging.error("request failed: %s", "TimeoutError")
            except Exception as exc:
                logging.error("request failed: %s", type(exc).__name__)
                self.close_connection = True
            finally:
                # After a 405, or any earlier error, an unread body must not
                # stay on the connection to be parsed as the next request.
                self._close_if_unread_body()

        def log_message(self, fmt, *args):
            # Drop anything after ? so a query is not written to the log.
            # Never raise: a broken format or a wild request line is dropped.
            try:
                text = fmt % args if args else str(fmt)
            except Exception:
                text = "unformattable log line"
            if "?" in text:
                text = text.split("?", 1)[0]
            logging.info(
                "%s %s",
                escape_controls(self.client_address[0]),
                escape_controls(text),
            )

        def log_request(self, code="-", size="-"):
            raw_path = getattr(self, "path", None) or "/"
            path = raw_path.split("?", 1)[0] or "/"
            command = getattr(self, "command", None) or "-"
            status = getattr(code, "value", code)
            logging.info(
                "%s %s %s %s",
                escape_controls(self.client_address[0]),
                escape_controls(command),
                escape_controls(path),
                status,
            )

        def version_string(self):
            return "Preached"

        def send_error(self, code, message=None, explain=None):
            """Fixed JSON. The request line is not echoed back to the client."""
            try:
                self.log_error("code %s", code)
            except Exception:
                logging.error("request failed: %s", "LogError")
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
            if self._has_unread_body():
                self.close_connection = True
                self.send_header("Connection", "close")
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
            if self._framing_problem() is not None:
                raise BadRequest("bad request")
            raw_length = self.headers.get("Content-Length")
            if raw_length is not None and int(raw_length) > MAX_BODY:
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
            # The socket peer, never X-Forwarded-For. /healthz uses this same
            # bucket. A proxy in front shares one bucket until a trusted-proxy
            # mode exists; that is not this process.
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
            self.close_connection = True
            self.send_response(405)
            self._security_headers()
            self.send_header("Allow", "GET, HEAD")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
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
    """Threaded server with a global cap and a per-client cap.

    ``ThreadingHTTPServer`` starts one thread per accepted connection. Over
    the cap, the connection is closed on the accept thread with a short 503
    and no handler thread is started.
    """

    allow_reuse_address = True
    # Handler threads are not daemons and are kept (block_on_close), so
    # neither server_close nor interpreter exit runs while a handler still
    # uses the index or the ONNX session. drain() stops them first.
    daemon_threads = False
    block_on_close = True
    max_connections = DEFAULT_MAX_CONNECTIONS
    max_connections_per_client = DEFAULT_MAX_CLIENT_CONNECTIONS
    header_deadline_s = HEADER_DEADLINE_S

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._conn_lock = threading.Lock()
        self._conn_total = 0
        self._conn_by_ip: dict[str, int] = {}
        self.max_connections = _positive_int(
            os.environ.get("PREACHED_MAX_CONNECTIONS"), DEFAULT_MAX_CONNECTIONS
        )
        self.max_connections_per_client = _positive_int(
            os.environ.get("PREACHED_MAX_CLIENT_CONNECTIONS"),
            DEFAULT_MAX_CLIENT_CONNECTIONS,
        )
        self.header_deadline_s = _positive_float(
            os.environ.get("PREACHED_HEADER_DEADLINE_S"), HEADER_DEADLINE_S
        )

    def _acquire_connection(self, ip: str) -> bool:
        with self._conn_lock:
            if self._conn_total >= self.max_connections:
                return False
            held = self._conn_by_ip.get(ip, 0)
            if held >= self.max_connections_per_client:
                return False
            self._conn_total += 1
            self._conn_by_ip[ip] = held + 1
            return True

    def _release_connection(self, ip: str) -> None:
        with self._conn_lock:
            self._conn_total = max(0, self._conn_total - 1)
            left = self._conn_by_ip.get(ip, 0) - 1
            if left <= 0:
                self._conn_by_ip.pop(ip, None)
            else:
                self._conn_by_ip[ip] = left

    def process_request(self, request, client_address) -> None:
        ip = client_address[0]
        if not self._acquire_connection(ip):
            self._reject_over_cap(request)
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._release_connection(ip)
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._release_connection(client_address[0])

    def _reject_over_cap(self, request) -> None:
        body = b'{"error":"unavailable"}'
        message = (
            b"HTTP/1.1 503 Service Unavailable\r\n"
            b"Content-Type: application/json; charset=utf-8\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
            b"Connection: close\r\n"
            b"Retry-After: 1\r\n"
            b"Cache-Control: no-store\r\n"
            b"\r\n" + body
        )
        try:
            request.settimeout(1)
            request.sendall(message)
        except OSError:
            pass

    def _live(self) -> dict:
        """Sockets with a handler running, and whether drain has begun.

        Created on first use (the way socketserver creates ``_threads``)."""
        return vars(self).setdefault("_live_state", {"lock": threading.Lock(), "socks": set(), "draining": False})

    def finish_request(self, request, client_address) -> None:
        # Runs on the handler thread. After drain has begun a new handler
        # serves nothing; process_request_thread still closes the socket.
        live = self._live()
        with live["lock"]:
            if live["draining"]:
                return
            live["socks"].add(request)
        try:
            super().finish_request(request, client_address)
        finally:
            with live["lock"]:
                live["socks"].discard(request)

    def drain(self, timeout_s: float = DRAIN_TIMEOUT_S) -> list:
        """Stop accepting and wait for every handler thread. Call after the
        serve loop has stopped. Returns the threads still alive at the bound.

        The listening socket closes first. A handler waiting for the next
        request on a keep-alive connection is woken with SHUT_RD (it reads
        EOF and ends); a search in progress finishes and sends its response.
        At half the bound the remaining sockets are shut both ways.
        """
        try:
            self.socket.close()
        except OSError:
            pass
        live = self._live()
        with live["lock"]:
            live["draining"] = True
            socks = list(live["socks"])
        for sock in socks:
            _shutdown_socket(sock, socket.SHUT_RD)
        threads = vars(self).get("_threads")  # set on the first request
        if threads is None:
            return []
        # A thread appended but never started (an exception on the accept
        # thread between the two) cannot be joined; socketserver's own join
        # would raise. Drop it here so server_close does not.
        for thread in list(threads):
            if thread.ident is None:
                threads.remove(thread)
                try:
                    self.shutdown_request(thread._args[0])
                except Exception:
                    pass
        deadline = time.monotonic() + timeout_s
        forced = False
        for thread in list(threads):
            while thread.is_alive():
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                if not forced and left <= timeout_s / 2:
                    forced = True
                    with live["lock"]:
                        socks = list(live["socks"])
                    for sock in socks:
                        _shutdown_socket(sock, socket.SHUT_RDWR)
                thread.join(min(left, 0.1))
        return [thread for thread in threads if thread.is_alive()]


def _shutdown_socket(sock, how: int) -> None:
    try:
        sock.shutdown(how)
    except OSError:
        pass


def make_server(app: App, host: str, port: int) -> PreachedServer:
    return PreachedServer((host, port), make_handler(app))


def serve_forever(server: PreachedServer) -> None:
    host, port = server.server_address[:2]
    print(f"PREACHED_RSS_BYTES {rss_bytes() or 0}", flush=True)
    print(f"PREACHED_LISTENING http://{host}:{port}", flush=True)
    logging.info("listening on http://%s:%s", host, port)
    server.serve_forever()


def prepare_church(*, church_index: Path | None, church_library: str | None) -> None:
    """Refuse an explicit classic as the church. Open nothing, log nothing.

    ``--church-library`` and ``--church-index`` are checked by name and path
    only (``library.classic_church_refusal``: slug, realpath, inode,
    hardlink count); no file is opened, so no ``-shm`` or ``-wal`` appears
    beside it. The index directory is not scanned for a ``role=church``
    mark. Startup output is the same with or without a church.

    TODO(post-#12): open the church file through #12's gate and per-request
    ``visible_sql`` (``search.Searcher(gated=True)``), withhold audio on
    flagged passages, apply the source_url rule to hits, and reload it with
    #10's index stamp. Church confidence is ``abstain.church_confidence``
    (unrated) until a church floor exists.
    """
    refusal = classic_church_refusal(church_library, church_index)
    if refusal:
        raise SystemExit(refusal)


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


def writable_problem(index: Path) -> str | None:
    """Why ``index`` is too writable to serve, or None.

    The file and the directory that holds it must not be group- or
    world-writable. When that directory is named ``index`` (a bundle, or
    ``/cache/index``), its parent is checked too. That parent is the bundle
    root. A loose file under a temp directory is not walked up into ``/tmp``.
    ``serve.sh`` does not chmod these paths; a world-writable bundle is
    refused here instead of being repaired.
    """
    index = Path(index)
    targets: list[tuple[Path, str]] = [
        (index, "index"),
        (index.parent, "index directory"),
    ]
    if index.parent.name == "index":
        targets.append((index.parent.parent, "index parent directory"))
    for target, what in targets:
        try:
            st = os.stat(target)
        except OSError as exc:
            return f"cannot check {target} ({exc})"
        if st.st_mode & 0o022:
            return (
                f"{what} {target} is group- or world-writable "
                f"(mode {stat.S_IMODE(st.st_mode):o})"
            )
    return None


def check_servable(connection, library: str, index: Path, *, church_gate: bool = False) -> None:
    """SystemExit unless this file may be served as ``library``.

    Served: the Wesley index; an allow-listed public-domain library; and a
    church library ONLY when ``church_gate`` is true, which ``main`` sets only
    when a privacy config is loaded and the publish gate is on (every library
    but wesley is gated: ``App.gated``). Without both, church libraries are
    refused (fail closed).

    A classic (``--library spurgeon``/``edwards``) is served only from its
    canonical INDEX_DIR/<slug>.sqlite (``libraries.classic_index_problem``:
    realpath equality, no symlinks, owner and mode, one link, and the same
    checks on any -wal, -shm or -journal file next to it), and that file
    must carry the matching ``library`` marker. A marker anywhere else is
    not trusted.

    Wesley must look like the Wesley index: chunks, every sermon id
    ``wesley-*``, no ``videos`` table, no ``library`` marker, and only the
    tables and columns in WESLEY_SCHEMA (case-insensitive), so no column a
    church import or the review gate adds, in chunks or a side table.

    A group- or world-writable bundle is refused, not repaired. The bundle
    manifest is checked once at start by ``bundle_problem``, not here.
    """
    problem = writable_problem(index)
    if problem is not None:
        raise SystemExit(f"error: {problem}")
    tables = {row[0].lower() for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    marker = None
    if "meta" in tables:
        row = connection.execute("SELECT value FROM meta WHERE key = 'library'").fetchone()
        marker = row[0] if row is not None else None
    allowed = f"allowed: {', '.join((LIBRARY, *PUBLIC_DOMAIN))}"
    if library != LIBRARY and not is_public_domain(library):
        if not church_gate:
            raise SystemExit(
                f"error: --library {library!r} refused: church libraries are served only with a privacy "
                "config ($PREACHED_PRIVACY) and the publish gate on."
            )
        return
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
    # No PREACHED_ALLOW_ROOT. Root is refused here, not only in serve.sh.
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise SystemExit("refusing to serve as root")
    # SIGTERM (systemd stop, serve.sh's parent) is handled at the top of this
    # file as SystemExit(0) in every phase, so the socket and index close and
    # atexit removes the bytecode prefix.
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
        help="Your church's library slug. Accepted and checked (never a classic); not served until the publish gate is wired",
    )
    parser.add_argument(
        "--church-index",
        type=Path,
        default=None,
        help="SQLite file for your church. Accepted and checked (never a classic); not opened",
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
    parser.add_argument(
        "--embed-backend",
        choices=("onnx", "torch"),
        default=None,
        help=f"query embedder (default {DEFAULT_EMBED_BACKEND}, or PREACHED_EMBED_BACKEND)",
    )
    parser.add_argument("--onnx-variant", choices=("fp32",), default=None)
    parser.add_argument("--ort-threads", type=int, default=None, help="ONNX Runtime intra-op threads")
    args = parser.parse_args(argv)
    try:
        # Always none (Patrick's decision); a stale play/shifted setting stops here.
        resolve_flagged_audio(default_config().flagged_audio)
    except (ValueError, OSError) as exc:
        raise SystemExit(f"flagged audio policy: {exc}") from exc
    if args.model not in RUNTIME_MODELS:
        why = "eval-only, not available to the server" if args.model in MODELS else "unknown"
        raise SystemExit(f"model {args.model}: {why}")
    library = args.library.strip()
    if not LIBRARY_SLUG.fullmatch(library):
        raise SystemExit("library must be a short slug: lowercase letters, digits, and hyphens")
    church_library = args.church_library.strip() if args.church_library else None
    if church_library is not None and not LIBRARY_SLUG.fullmatch(church_library):
        raise SystemExit("church library must be a short slug: lowercase letters, digits, and hyphens")
    # Every library but wesley is gated (App.gated, no switch turns it off).
    # A church library is served only with a privacy config loaded.
    church = library != LIBRARY and not is_public_domain(library)
    church_gate = False
    if church:
        try:
            required_config()  # $PREACHED_PRIVACY, the same config App reads
        except MissingConfig as exc:
            raise SystemExit(
                f"error: --library {library!r} refused: {exc}. Only {', '.join((LIBRARY, *PUBLIC_DOMAIN))} "
                "are served without one."
            ) from exc
        except (ValueError, OSError) as exc:
            raise SystemExit(f"error: privacy config: {exc}") from exc
        church_gate = True
    index = args.index if args.index is not None else INDEX_DIR / f"{library}.sqlite"
    if library == LIBRARY and args.index is None:
        index = INDEX_PATH
    # The file checked must be the file opened: same (st_dev, st_ino) before
    # the hash below, after the open and checks, and before every reload.
    identity = file_identity(index)
    # From a bundle: MANIFEST.sha256 must parse and match, and the index must
    # be the bundle's own. A checkout (.git, no build stamp) skips this; a
    # tree that is neither is refused. serve.sh ran the same check before
    # importing this module; this repeats it for any other launcher.
    problem = bundle_problem(index)
    if problem is not None:
        raise SystemExit(f"error: {problem}")
    bundle = is_bundle()
    if bundle:
        # Only the bundle's own hashed model/, only the ONNX backend (torch
        # and preached.embed are not shipped).
        problem = onnx_dir_problem(ROOT, os.environ.get(ONNX_ROOT_ENV))
        if problem is not None:
            raise SystemExit(f"error: {problem}")
        os.environ[ONNX_ROOT_ENV] = str(ROOT / "model")
        backend = (args.embed_backend or os.environ.get("PREACHED_EMBED_BACKEND") or "onnx").strip().lower()
        if backend != "onnx":
            raise SystemExit("error: a bundle serves only the onnx embed backend")
    # Refuses wesley / spurgeon / edwards as the church. Opens nothing.
    # The church side stays empty until PR #12's gate serves it.
    prepare_church(church_index=args.church_index, church_library=church_library)
    try:
        connection = open_readonly(index, check_same_thread=False)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    except UnsafeSidecar as exc:
        raise SystemExit(str(exc)) from exc

    def servable(conn) -> None:
        check_servable(conn, library, index, church_gate=church_gate)
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
        frozen=bundle,
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
    serve_until_stopped(server, app, connection)


def serve_until_stopped(server: PreachedServer, app: App, connection) -> None:
    """Serve until SIGTERM (or Ctrl-C), then stop in order: stop accepting,
    wait for the handler threads (bounded), close the index, release the
    ONNX session. Closing the index under a running handler segfaulted, and
    finalising with a session mid-run aborted in ONNX Runtime.

    Run as a script, SIGTERM and SIGINT stop the serve loop from another
    thread (``_on_stop_signal``). A SIGTERM that arrived before this point,
    even one an import swallowed, means nothing is served.
    """
    _STOP["server"] = server
    if _SCRIPT and threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _on_stop_signal)
    try:
        if not _STOP["requested"]:
            serve_forever(server)
    except KeyboardInterrupt:
        pass
    finally:
        _STOP["stopping"] = True  # a later SIGTERM changes nothing
        logging.info("stopping")
        stuck = server.drain()
        if stuck:
            # Closing the index or the session now could crash the process.
            # Leave both open; interpreter exit waits for these threads.
            logging.error("%d handler thread(s) still running after %.0fs; index left open", len(stuck), DRAIN_TIMEOUT_S)
        else:
            server.server_close()
            connection.close()
            app.close_embedder()
    if stuck:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:  # Ctrl-C before serving: no traceback
        sys.exit(130)
