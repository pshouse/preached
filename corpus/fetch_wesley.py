"""Download Wesley's sermons from CCEL and write /cache/corpus/wesley/.

Commits only the metadata catalog (corpus/catalog.json). The full text stays
in /cache.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from preached.corpus import fetch_corpus  # noqa: E402
from preached.paths import SERMONS_JSONL, catalog_path  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download the CCEL files")
    parser.add_argument("--accept-new-text", action="store_true",
                        help="accept a CCEL text whose sha256 differs from corpus/catalog.json")
    args = parser.parse_args()
    catalog = fetch_corpus(force=args.force, accept_new_text=args.accept_new_text)
    print(
        f"wrote {catalog['sermon_count']} sermons, {catalog['word_count']} words\n"
        f"  text: {SERMONS_JSONL}\n"
        f"  catalog: {catalog_path()}\n"
        f"  sha256: {catalog['sha256_text']}"
    )


if __name__ == "__main__":
    main()
