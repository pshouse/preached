"""Start the server on a random port and run one search.

BM25 by default, so this does not load the embedding model or fetch audio.
``--embed`` loads the configured model on CPU.

  uv run python scripts/smoke_server.py
  uv run python scripts/smoke_server.py --embed
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from app.server import build_app, make_server  # noqa: E402
from preached.models import DEFAULT_MODEL  # noqa: E402
from preached.paths import INDEX_PATH  # noqa: E402
from preached.store import open_readonly_or_exit  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Start Preached and run one search.")
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    parser.add_argument("--query", default="Christian perfection")
    parser.add_argument("--embed", action="store_true", help="Load the embedding model on CPU")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args(argv)

    connection = open_readonly_or_exit(args.index, check_same_thread=False)
    app = build_app(
        connection,
        model_key=args.model,
        bm25_only=not args.embed,
        hosts={"127.0.0.1", "localhost"},
        static_dir=ROOT / "app" / "static",
    )
    server = make_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        health_url = f"http://127.0.0.1:{port}/healthz"
        health = None
        deadline = time.monotonic() + 30
        while health is None:
            try:
                with urllib.request.urlopen(health_url, timeout=5) as response:
                    health = json.loads(response.read())
            except (urllib.error.URLError, TimeoutError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
        if not health.get("ok"):
            raise SystemExit(f"health check failed: {health}")
        params = urllib.parse.urlencode(
            {"q": args.query, "k": 3, "mode": "hybrid" if args.embed else "bm25", "library": "wesley"}
        )
        search_url = f"http://127.0.0.1:{port}/api/search?{params}"
        with urllib.request.urlopen(search_url, timeout=120) as response:
            payload = json.loads(response.read())
        results = payload.get("results") or []
        if not results:
            raise SystemExit(f"no results for {args.query!r}: {payload.get('note')}")
        first = results[0]
        print(f"port {port}")
        print(f"mode {payload.get('mode')} note {payload.get('note')}")
        print(f"{first.get('sermon_id')} {first.get('sermon_title')}")
        print((first.get("text") or "")[:180])
    finally:
        server.shutdown()
        server.server_close()
        connection.close()


if __name__ == "__main__":
    main()
