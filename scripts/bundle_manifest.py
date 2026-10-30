#!/usr/bin/env python3
"""Write MANIFEST.sha256 for a bundle directory. Stdlib only.

Every regular file except the manifest itself is listed as
``<sha256><two spaces><relative posix path>``, sorted by path. The same
bytes produce the same manifest. Modes and mtimes are not recorded.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SKIP_NAMES = {"MANIFEST.sha256", "KILL"}


def iter_files(root: Path) -> list[str]:
    found: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        name = path.name
        if name in SKIP_NAMES or name.endswith(".pyc"):
            continue
        if "/__pycache__/" in f"/{rel}/" or rel.startswith(".venv/") or rel == ".venv":
            continue
        found.append(rel)
    return sorted(found)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_text(root: Path) -> str:
    lines = [f"{sha256(root / rel)}  {rel}\n" for rel in iter_files(root)]
    return "".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: bundle_manifest.py DIRECTORY", file=sys.stderr)
        return 2
    root = Path(argv[1]).resolve()
    if not root.is_dir():
        print("not a directory", file=sys.stderr)
        return 2
    text = manifest_text(root)
    target = root / "MANIFEST.sha256"
    target.write_text(text)
    print(hashlib.sha256(text.encode()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
