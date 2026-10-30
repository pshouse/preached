#!/usr/bin/env python3
"""Import a YouTube channel into a Preached library.

    uv run import/youtube.py <channel-url> --library <slug> [--limit N] [--since YYYY-MM-DD] [--dry-run]

The index is /cache/index/<slug>.sqlite. Audio working files go under
/cache/youtube/<slug>/ and are deleted after a successful import
(--keep-audio leaves them). They are not committed. See the README.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from preached.youtube.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
