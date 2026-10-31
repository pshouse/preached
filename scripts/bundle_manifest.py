#!/usr/bin/env python3
"""Write MANIFEST.sha256 for a bundle directory. Stdlib only.

Every regular file except the manifest itself is listed as
``<sha256><two spaces><relative posix path>``, sorted by path. The same
bytes produce the same manifest. Modes and mtimes are not recorded.
There are no comment lines: the server (``app.server.bundle_problem``)
refuses any line that is not a hash and a path.

Also copies an index with SQLite's backup API (so a WAL is included) and
strips int8 from a bundled ONNX manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
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
    return "".join(f"{sha256(root / rel)}  {rel}\n" for rel in iter_files(root))


def copy_index(source: Path, dest: Path) -> None:
    """Copy ``source`` with the backup API and leave a DELETE-mode database.

    ``cp`` of a WAL database drops the ``-wal`` file, and a WAL database
    cannot be opened read-only from a directory the process cannot write.
    The bundled file is one regular file, journal mode DELETE, with no
    ``-wal`` or ``-shm`` beside it. Two copies of an unchanged source match.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    # lexists: a dangling symlink is removed too, or the connect below would
    # follow it and create its target.
    if os.path.lexists(dest):
        dest.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        extra = Path(str(dest) + suffix)
        if os.path.lexists(extra):
            extra.unlink()
    # Read-only (store.open_readonly: mode=ro, query_only, sidecars checked)
    # so the backup cannot checkpoint or write the live index, or Wesley
    # through a -shm hardlinked to it. A WAL source still needs a writable
    # directory for the -shm file. Imported here: the manifest is stdlib only.
    from preached.store import open_readonly_or_exit

    src = open_readonly_or_exit(source)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
            mode = dst.execute("PRAGMA journal_mode=DELETE").fetchone()
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()
    if mode is None or mode[0] != "delete":
        raise SystemExit(f"bundled index journal mode is {mode!r}, not delete")
    for suffix in ("-wal", "-shm"):
        extra = Path(str(dest) + suffix)
        if extra.exists():
            extra.unlink()


def strip_int8_manifest(path: Path) -> None:
    """Drop int8 from a JSON ONNX manifest. Non-JSON is left unchanged.

    Tests use a stand-in manifest that is not JSON. A real manifest is JSON
    and must not name ``model.int8.onnx`` after this runs.
    """
    raw = path.read_text(encoding="utf-8")
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(manifest, dict):
        return
    variants = manifest.get("variants")
    if isinstance(variants, dict):
        manifest["variants"] = {
            key: value
            for key, value in variants.items()
            if "int8" not in key and "int8" not in str(value)
        }
    files = manifest.get("files")
    if isinstance(files, dict):
        manifest["files"] = {
            key: value for key, value in files.items() if "int8" not in key
        }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    args = argv[1:]
    if len(args) != 1:
        print("usage: bundle_manifest.py DIRECTORY", file=sys.stderr)
        return 2
    root = Path(args[0]).resolve()
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
