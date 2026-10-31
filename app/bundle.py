"""Bundle or checkout, and the bundle's manifest check. Stdlib only.

``scripts/serve.sh`` runs this file as a script, ``python -I -B
app/bundle.py ROOT INDEX``, before any bundle module is imported. The
check therefore runs before the code it hashes. ``app.server.main`` runs the
same check again for a server started some other way.

A tree is one of:

- a bundle: ``PREACHED_BUNDLE`` (the build stamp) exists. The stamp must be
  listed in MANIFEST.sha256 and every check below applies.
- a checkout: no stamp, a ``.git`` entry at the root, and none of the bundle
  markers. Nothing is hashed.
- anything else is refused. A bundle with its stamp and markers deleted is
  not a checkout.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The build stamp. scripts/build-bundle.sh writes it before the manifest.
BUILD_STAMP = "PREACHED_BUNDLE"
STAMP_HEADER = "preached-bundle 1"
# A built bundle has these at its root. A source checkout has none of them.
BUNDLE_MARKERS = (BUILD_STAMP, "MANIFEST.sha256", "index", "model", "requirements-serve.txt")
# "<sha256>  <relative path>", as scripts/bundle_manifest.py writes it.
MANIFEST_LINE = re.compile(r"([0-9a-f]{64})  ([^\x00-\x1f\x7f\\]+)")
ONNX_ROOT_ENV = "PREACHED_ONNX_DIR"


def layout(root: Path = ROOT) -> str | None:
    """"bundle", "checkout", or None when the tree is neither."""
    root = Path(root)
    if os.path.lexists(root / BUILD_STAMP):
        return "bundle"
    if os.path.lexists(root / ".git") and not any(os.path.lexists(root / name) for name in BUNDLE_MARKERS):
        return "checkout"
    return None


def is_bundle(root: Path = ROOT) -> bool:
    """False only for a checkout. A tree that is neither counts as a bundle."""
    return layout(root) != "checkout"


def stamp_text(library: str, revision: str) -> str:
    return f"{STAMP_HEADER}\nlibrary {library}\nmodel-revision {revision}\n"


def _manifest_entries(manifest: Path) -> dict[str, str] | str:
    """Path -> sha256 from MANIFEST.sha256, or why it is unusable.

    Every line must be a hash and a relative path, sorted, no repeats, and
    the file must end with a newline. There are no comment lines.
    """
    if manifest.is_symlink() or not manifest.is_file():
        return f"{manifest} is missing"
    try:
        text = manifest.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return f"cannot read {manifest} ({type(exc).__name__})"
    if not text.endswith("\n") or text == "\n":
        return f"{manifest} is not a bundle manifest"
    entries: dict[str, str] = {}
    previous = ""
    for number, line in enumerate(text[:-1].split("\n"), 1):
        match = MANIFEST_LINE.fullmatch(line)
        if match is None:
            return f"{manifest} line {number} is not '<sha256>  <path>'"
        digest, rel = match.groups()
        parts = rel.split("/")
        if rel.startswith("/") or any(part in ("", ".", "..") for part in parts):
            return f"{manifest} line {number} is not a plain relative path"
        if rel <= previous:
            return f"{manifest} line {number} is out of order or repeated"
        previous = rel
        entries[rel] = digest
    return entries


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def bundle_problem(index: Path, root: Path = ROOT) -> str | None:
    """Why this tree may not serve ``index``, or None. A checkout returns None.

    A tree that is neither a bundle nor a checkout is refused. From a
    bundle, MANIFEST.sha256 must exist and parse and must list the build
    stamp; every file it lists must be a regular file with that sha256; no
    other file may sit in the tree (only ``.venv/`` and the kill file
    ``KILL`` are allowed beside it, so any ``__pycache__`` or ``*.pyc`` is
    refused); and the index must resolve to a listed file under ``index/``
    in this bundle. Nothing here can be switched off: there is no marker,
    flag or environment variable that skips it.
    """
    root = Path(root)
    kind = layout(root)
    if kind == "checkout":
        return None
    root = root.resolve()
    if kind is None:
        return (
            f"{root} has no build stamp {BUILD_STAMP} and is not a git checkout (no .git, or bundle "
            "files present); refusing to serve"
        )
    manifest = root / "MANIFEST.sha256"
    entries = _manifest_entries(manifest)
    if isinstance(entries, str):
        return f"bundle {root}: {entries}; refusing to serve"
    if BUILD_STAMP not in entries:
        return f"bundle {root}: the build stamp {BUILD_STAMP} is not in {manifest}; refusing to serve"
    real = Path(os.path.realpath(index))
    try:
        rel_index = real.relative_to(root).as_posix()
    except ValueError:
        return f"index {index} is outside the bundle {root}; refusing to serve"
    if not rel_index.startswith("index/") or rel_index not in entries:
        return f"index {index} is not a bundled index listed in {manifest}; refusing to serve"
    for rel, digest in entries.items():
        path = root / rel
        try:
            st = os.lstat(path)
        except OSError:
            return f"bundle file {rel} is missing; refusing to serve"
        if not stat.S_ISREG(st.st_mode):
            return f"bundle file {rel} is not a regular file; refusing to serve"
        try:
            actual = _sha256_of(path)
        except OSError as exc:
            return f"cannot read bundle file {rel} ({type(exc).__name__}); refusing to serve"
        if actual != digest:
            return f"bundle file {rel} does not match {manifest}; refusing to serve"
    try:
        stamp = (root / BUILD_STAMP).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return f"cannot read the build stamp ({type(exc).__name__}); refusing to serve"
    if stamp.split("\n", 1)[0] != STAMP_HEADER:
        return f"bundle {root}: {BUILD_STAMP} is not a build stamp; refusing to serve"
    for current, dirs, files in os.walk(root):
        here = Path(current)
        # os.walk lists a symlink to a directory under dirs and does not
        # follow it. It is not a listed file, so it counts as unlisted.
        # ``.venv`` at the root is uv's (a directory or a link to one). It is
        # outside the manifest and is a trust boundary (docs/DEPLOY.md).
        dirs[:] = [name for name in dirs if not (here == root and name == ".venv")]
        for name in dirs:
            if name == "__pycache__":
                rel = (here / name).relative_to(root).as_posix()
                return f"bundle has bytecode at {rel}; refusing to serve (it could run in place of the hashed source)"
        linked = [name for name in dirs if (here / name).is_symlink()]
        dirs[:] = sorted(name for name in dirs if name not in linked)
        for name in files + linked:
            rel = (here / name).relative_to(root).as_posix()
            if rel in entries or rel in ("MANIFEST.sha256", "KILL"):
                continue
            return f"bundle file {rel} is not in {manifest}; refusing to serve"
    return None


def onnx_dir_problem(root: Path = ROOT, value: str | None = None) -> str | None:
    """Why a bundle may not load ONNX files from ``value``, or None.

    A bundle loads only its own ``model/`` (hashed in the manifest). Another
    directory could hold an older revision, or nothing, which drops search
    to BM25 without a refusal. Unset is fine; ``main`` sets it to
    ``ROOT/model``. A checkout returns None.
    """
    if not is_bundle(root):
        return None
    if not value:
        return None
    own = os.path.realpath(Path(root) / "model")
    if os.path.realpath(value) != own:
        return f"{ONNX_ROOT_ENV} must be the bundle's own model directory, not {value}; refusing to serve"
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python -I -B app/bundle.py ROOT INDEX", file=sys.stderr)
        return 2
    root = Path(argv[1])
    problem = bundle_problem(Path(argv[2]), root=root) or onnx_dir_problem(root, os.environ.get(ONNX_ROOT_ENV))
    if problem is not None:
        print(f"error: {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
