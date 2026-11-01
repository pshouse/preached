"""Hash the server's responses, one hash per set, for the response-parity gate.

    uv run python scripts/parity_hash.py --index PATH [--strip why] [--expect SET=HASH ...]

Two apps are built the way ``app/server.py`` builds them (``build_app``,
read-only index, ``check_servable`` first): one with a church side, one
without. The church file is the synthetic fixture from the tests
(``tests/test_church_wire.build_church``), written to a new temp dir; no real
church file is opened. The church side searches it keyword only, because its
fixture vectors are not the server model's.

The inputs are ``eval/parity/requests.json`` (93 frozen eval queries, the
``compare_responses.py`` probe paths) and ``QUERIES`` from
``tests/test_church_wire.py``. Each set is a list of records:

- ``search+sermon``: ``/api/search?q=Q&k=10`` per query, then
  ``/api/sermon/ID`` for every sermon id those results name, sorted;
- ``side``: ``/api/side?q=Q&k=5`` per query;
- ``church``: per church query, ``/api/search?q=C&library=sample&k=10``
  and ``/api/side?q=C&k=10``;
- ``http``: ``/healthz``, the probes, then search+sermon, side and church;
- ``no-church``: the ``http`` list against the app with no church side
  (sermon ids from its own results);
- ``in-process``: ``App.health``, then ``App.search``, ``App.sermon`` and
  ``App.side`` for the same requests as ``http`` minus the probes, called
  directly on the church app (no HTTP);
- ``in-process-no-health``: ``in-process`` without ``App.health``.

All but the two in-process sets go over HTTP to the app served on an
ephemeral 127.0.0.1 port. An HTTP record is ``{"request", "status", "type",
"body"}``: ``type`` is the Content-Type, ``body`` the parsed JSON, or
``{"sha256": hex}`` of the bytes when it is not JSON. Date and other headers
are left out. An in-process record is ``{"call", "args", "result"}``;
a ``BadRequest`` is ``{"error", "status"}``.

Canonical form: ``took_ms`` and every ``--strip`` name are dropped as dict
keys at any depth, then ``json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=False, allow_nan=False)`` encoded as UTF-8. A set's hash is the
first 16 hex digits of the SHA-256 of its list. Floats keep Python's
shortest round-trip repr.

Prints ``SET HASH`` lines in a fixed order. stderr gets the index_version,
model_sha256 and harness hash (SHA-256 of this file, a NUL, then the
inputs file; first 16 hex digits). ``--expect SET=HASH`` (16 hex digits) exits 1 on any
mismatch. A ``--strip`` name that is no dict key in any set exits 1 naming it;
a non-positive-int ``k`` or a duplicate query in the inputs is refused. The rate limits are lifted and ``PREACHED_DISABLED``,
``PREACHED_KILL_FILE`` and ``PREACHED_TRUSTED_PROXIES`` are unset while it
runs. Importing the test builders arms ``tests/cache_guard`` (tool caches
go to a temp dir).
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import urllib.parse
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("src", ""):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

from app.server import (  # noqa: E402
    LIBRARY,
    STATIC_DIR,
    BadRequest,
    build_app,
    check_servable,
    make_server,
)
from preached.models import DEFAULT_MODEL  # noqa: E402
from preached.store import open_readonly  # noqa: E402

INPUTS = ROOT / "eval" / "parity" / "requests.json"
SETS = ("http", "no-church", "in-process", "in-process-no-health", "search+sermon", "side", "church")
ALWAYS_STRIP = ("took_ms",)
CHURCH_SLUG = "sample"
UNLIMITED = "1000000000"
RATE_ENV = (
    "PREACHED_RATE_LIMIT",
    "PREACHED_GLOBAL_RATE_LIMIT",
    "PREACHED_HEALTH_RATE_LIMIT",
    "PREACHED_HEALTH_GLOBAL_RATE_LIMIT",
)
UNSET_ENV = ("PREACHED_DISABLED", "PREACHED_KILL_FILE", "PREACHED_TRUSTED_PROXIES")


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()[:16]


def strip(value, names: frozenset):
    if isinstance(value, dict):
        return {k: strip(v, names) for k, v in value.items() if k not in names}
    if isinstance(value, (list, tuple)):
        return [strip(v, names) for v in value]
    return value


def keys_in(value, found: set) -> set:
    if isinstance(value, dict):
        found.update(value)
        for item in value.values():
            keys_in(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys_in(item, found)
    return found


def check_strip(parts: dict, requested) -> None:
    """Refuse a ``--strip`` name that is a key nowhere in any set (a typo would hash unstripped)."""
    present = keys_in(list(parts.values()), set())
    for name in requested:
        if name not in ALWAYS_STRIP and name not in present:
            raise SystemExit(f"--strip {name}: no such key in any response")


def load_inputs(path: Path) -> dict:
    """Read the request file; refuse a ``k`` that is not a positive int and duplicate queries."""
    inputs = json.loads(path.read_text(encoding="utf-8"))
    for field in ("k", "side_k"):
        value = inputs.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise SystemExit(f"{path}: {field} must be a positive integer, got {value!r}")
    seen = set()
    for item in inputs["queries"]:
        if item["q"] in seen:
            raise SystemExit(f"{path}: duplicate query {item['q']!r}")
        seen.add(item["q"])
    return inputs


def harness_sha256(inputs: Path) -> str:
    data = Path(__file__).read_bytes() + b"\0" + inputs.read_bytes()
    return hashlib.sha256(data).hexdigest()[:16]


def _assert_under_temp(path: Path) -> Path:
    resolved = path.resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    if resolved == temp or temp not in resolved.parents:
        raise SystemExit(f"refusing to remove {resolved}: not under {temp}")
    return resolved


@contextmanager
def _serving_env():
    saved = {name: os.environ.get(name) for name in (*RATE_ENV, *UNSET_ENV)}
    for name in RATE_ENV:
        os.environ[name] = UNLIMITED
    for name in UNSET_ENV:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def search_path(query: str, k: int, library: str | None = None) -> str:
    params = {"q": query, "k": str(k)}
    if library is not None:
        params["library"] = library
    return "/api/search?" + urllib.parse.urlencode(params)


def side_path(query: str, k: int) -> str:
    return "/api/side?" + urllib.parse.urlencode({"q": query, "k": str(k)})


def sermon_ids(records) -> list[str]:
    found = set()
    for record in records:
        body = record.get("body") if "body" in record else record.get("result")
        if isinstance(body, dict):
            found.update(hit["sermon_id"] for hit in body.get("results") or [])
    return sorted(found)


def plan(inputs: dict, church_queries) -> dict:
    k, side_k = inputs["k"], inputs["side_k"]
    queries = [item["q"] for item in inputs["queries"]]
    return {
        "search": [(search_path(q, k), ("search", q, k, None)) for q in queries],
        "side": [(side_path(q, side_k), ("side", q, side_k)) for q in queries],
        "church": [
            request
            for q in church_queries
            for request in (
                (search_path(q, k, CHURCH_SLUG), ("search", q, k, CHURCH_SLUG)),
                (side_path(q, k), ("side", q, k)),
            )
        ],
    }


def http_get(port: int, path: str) -> dict:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    try:
        connection.request("GET", path, headers={"Connection": "close"})
        response = connection.getresponse()
        data = response.read()
        kind = response.getheader("Content-Type") or ""
        status = response.status
    finally:
        connection.close()
    if kind.startswith("application/json"):
        body = json.loads(data)
    else:
        body = {"sha256": hashlib.sha256(data).hexdigest()}
    return {"request": path, "status": status, "type": kind, "body": body}


def http_sets(app, inputs: dict, requests: dict) -> dict:
    server = make_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        get = lambda path: http_get(port, path)  # noqa: E731
        health = [get("/healthz")]
        probes = [get(path) for path in inputs["probes"]]
        searches = [get(path) for path, _ in requests["search"]]
        sermons = [get("/api/sermon/" + urllib.parse.quote(sid, safe="")) for sid in sermon_ids(searches)]
        side = [get(path) for path, _ in requests["side"]]
        church = [get(path) for path, _ in requests["church"]]
    finally:
        server.shutdown()
        server.server_close()
    return {
        "health": health,
        "all": health + probes + searches + sermons + side + church,
        "search+sermon": searches + sermons,
        "side": side,
        "church": church,
    }


def call(app, name: str, *args) -> dict:
    try:
        if name == "health":
            result = app.health()
        elif name == "search":
            query, k, library = args
            result = app.search(query, k, "hybrid", library=library)
        elif name == "sermon":
            result = app.sermon(*args)
        else:
            query, k = args
            result = app.side(query, k, "hybrid")
    except BadRequest as exc:
        result = {"error": str(exc), "status": exc.status}
    return {"call": name, "args": list(args), "result": result}


def in_process(app, requests: dict) -> tuple[list, list]:
    run = lambda item: call(app, item[0], *item[1:])  # noqa: E731
    health = [call(app, "health")]
    searches = [run(spec) for _, spec in requests["search"]]
    sermons = [call(app, "sermon", sid) for sid in sermon_ids(searches)]
    rest = [run(spec) for _, spec in requests["side"] + requests["church"]]
    return health, searches + sermons + rest


def open_app(index: Path, args, loader, church: Path | None):
    connection = open_readonly(index, check_same_thread=False)
    try:
        check_servable(connection, args.library, index)
        side = {}
        if church is not None:
            side = {
                "church_connection": open_readonly(church, check_same_thread=False),
                "church_library": CHURCH_SLUG,
            }
        app = build_app(
            connection,
            model_key=args.model,
            bm25_only=args.bm25_only,
            hosts={"127.0.0.1"},
            static_dir=STATIC_DIR,
            loader=loader,
            embed_backend=args.embed_backend,
            library=args.library,
            rate_limit=int(UNLIMITED),
            **side,
        )
    except BaseException:
        connection.close()
        raise
    return app


def close_app(app) -> None:
    app.close_embedder()
    for connection in (getattr(app, "church_connection", None), app.connection):
        if connection is not None:
            connection.close()


def compute(index: Path, args, loader=None) -> tuple[dict, dict]:
    """``(hashes, about)``: one hash per set, and what the gate records beside them."""
    from tests.test_church_wire import QUERIES, build_church

    inputs = load_inputs(args.inputs)
    names = frozenset((*ALWAYS_STRIP, *args.strip))
    requests = plan(inputs, QUERIES)
    scratch = Path(tempfile.mkdtemp(prefix="parity-church-"))
    try:
        church_path = scratch / f"{CHURCH_SLUG}.sqlite"
        build_church(church_path)
        with _serving_env():
            app = open_app(index, args, loader, church_path)
            try:
                served = http_sets(app, inputs, requests)
                health, calls = in_process(app, requests)
            finally:
                close_app(app)
            bare = open_app(index, args, loader, None)
            try:
                no_church = http_sets(bare, inputs, requests)
            finally:
                close_app(bare)
    finally:
        shutil.rmtree(_assert_under_temp(scratch))
    parts = {
        "http": served["all"],
        "no-church": no_church["all"],
        "in-process": health + calls,
        "in-process-no-health": calls,
        "search+sermon": served["search+sermon"],
        "side": served["side"],
        "church": served["church"],
    }
    check_strip(parts, args.strip)
    hashes = {name: digest(strip(parts[name], names)) for name in SETS}
    about = {
        "index_version": health[0]["result"].get("index_version"),
        "model_sha256": health[0]["result"].get("model_sha256"),
        "harness": harness_sha256(args.inputs),
        "strip": ",".join(sorted(names)),
    }
    return hashes, about


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Hash server responses for the response-parity gate.")
    parser.add_argument("--index", type=Path, required=True, help="classic SQLite index, opened read-only")
    parser.add_argument("--library", default=LIBRARY)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--bm25-only", action="store_true")
    parser.add_argument("--embed-backend", choices=("onnx", "torch"), default=None)
    parser.add_argument("--inputs", type=Path, default=INPUTS)
    parser.add_argument(
        "--strip", action="append", default=[], metavar="FIELD", help="drop this key at any depth (repeatable)"
    )
    parser.add_argument(
        "--expect", action="append", default=[], metavar="SET=HASH", help="exit 1 unless SET hashes to HASH"
    )
    args = parser.parse_args(argv)
    expected = {}
    for item in args.expect:
        name, _, value = item.partition("=")
        if name not in SETS or not re.fullmatch(r"[0-9a-f]{16}", value):
            parser.error(f"--expect {item!r}: want SET=HASH (16 lowercase hex digits), SET one of {', '.join(SETS)}")
        expected[name] = value
    args.expected = expected
    return args


def main(argv: list[str] | None = None, *, loader=None) -> int:
    """``loader`` replaces the query-embedder loader (tests pass a fixture one)."""
    args = parse_args(argv)
    hashes, about = compute(args.index, args, loader)
    for name in SETS:
        print(f"{name} {hashes[name]}")
    print(" ".join(f"{key}={value}" for key, value in about.items()), file=sys.stderr)
    failed = [name for name, value in args.expected.items() if hashes[name] != value]
    for name in failed:
        print(f"MISMATCH {name}: got {hashes[name]}, expected {args.expected[name]}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
