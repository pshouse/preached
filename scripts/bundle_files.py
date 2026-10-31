#!/usr/bin/env python3
"""List the files a serve bundle ships, or check a built bundle imports.

Run with ``python -I`` so neither PYTHONPATH nor the current directory adds
a module search path. The root to import from is passed as an argument and
put on ``sys.path`` here.

    python -I scripts/bundle_files.py list SOURCE
    python -I scripts/bundle_files.py check BUNDLE

``list`` imports the serve entry points from SOURCE and prints every
``app`` and ``preached`` module they load, every data directory inside a
loaded package (``preached/privacy_data``), and the fixed non-Python files
below. A new module the server imports is picked up without editing
``build-bundle.sh``. A ``preached`` import written inside a function (loaded
lazily, so not seen by the import) must name a loaded module or a module in
BUILD_ONLY; otherwise the list fails.

Shipped code may not use ``importlib`` or ``__import__``: an import by
string is invisible to that scan, so the list fails on either.

``check`` imports the same entry points from BUNDLE and fails unless every
loaded ``app`` or ``preached`` module's file is inside BUNDLE.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# What app/server.py loads, including the ONNX backend it loads lazily.
SERVE_MODULES = (
    "app.server",
    "preached.backends",
    "preached.onnx_embed",
    "preached.artifacts",
    "preached.libraries",
)
# Lazy imports on paths the bundle never takes (the torch backend).
BUILD_ONLY = frozenset({"preached.torch_embed", "preached.embed"})
OWN = ("app", "preached")

# Not Python modules, read by path at serve time or by the operator.
STATIC_FILES = (
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "AGENTS.md",
    ".python-version",
    "ingest/manifest/spurgeon.jsonl",
    "ingest/manifest/spurgeon.provenance.json",
    "ingest/manifest/edwards.jsonl",
    "ingest/manifest/edwards.provenance.json",
    "search/models.toml",
    "search/abstain.toml",
    "scripts/serve.sh",
)
STATIC_DIRS = ("app/static",)


def _load(root: Path) -> dict[str, Path]:
    root = root.resolve()
    sys.path[:0] = [str(root), str(root / "src")]
    for name in SERVE_MODULES:
        __import__(name)
    loaded: dict[str, Path] = {}
    for name, module in sorted(sys.modules.items()):
        if name.split(".", 1)[0] not in OWN:
            continue
        origin = getattr(module, "__file__", None)
        if origin is None:
            raise SystemExit(f"module {name} has no file")
        loaded[name] = Path(origin).resolve()
    return loaded


def _is_module(name: str, source: Path) -> bool:
    parts = name.split(".")
    base = source / "src" if parts[0] == "preached" else source
    path = base.joinpath(*parts)
    return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()


def _imports(path: Path, package: str, source: Path) -> set[str]:
    """``app``/``preached`` modules imported anywhere in ``path``, lazily or not."""
    names: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - node.level + 1]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            names.add(module)
            # ``from preached import privacy`` names a module too.
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return {
        name for name in names if name.split(".", 1)[0] in OWN and _is_module(name, source)
    }


def _dynamic_imports(path: Path) -> list[str]:
    """Lines in ``path`` that import by string: ``importlib`` or ``__import__``."""
    found: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        hit = False
        if isinstance(node, ast.Import):
            hit = any(alias.name.split(".", 1)[0] == "importlib" for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            hit = (node.module or "").split(".", 1)[0] == "importlib"
        elif isinstance(node, ast.Name):
            hit = node.id in ("__import__", "importlib")
        elif isinstance(node, ast.Attribute):
            hit = node.attr == "__import__"
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            hit = node.value == "__import__"
        if hit:
            found.append(f"{path.name}:{node.lineno}")
    return found


def _files(path: Path) -> list[Path]:
    return sorted(
        p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )


def list_files(source: Path) -> list[str]:
    source = source.resolve()
    loaded = _load(source)
    rels: set[str] = set()
    for name, origin in loaded.items():
        try:
            rels.add(origin.relative_to(source).as_posix())
        except ValueError:
            raise SystemExit(f"module {name} loaded from outside {source}") from None
    missing: list[str] = []
    for name, origin in loaded.items():
        if origin.suffix != ".py":
            continue
        package = name if origin.name == "__init__.py" else name.rpartition(".")[0]
        for target in _imports(origin, package, source):
            if target not in loaded and target not in BUILD_ONLY:
                missing.append(f"{name} -> {target}")
    if missing:
        raise SystemExit("serve code imports modules the bundle would not ship: " + ", ".join(sorted(missing)))
    dynamic = [
        hit for origin in loaded.values() if origin.suffix == ".py" for hit in _dynamic_imports(origin)
    ]
    if dynamic:
        raise SystemExit("serve code imports by string (importlib or __import__): " + ", ".join(sorted(dynamic)))
    # Data directories inside a loaded package (no __init__.py of their own).
    for name, origin in loaded.items():
        if origin.name != "__init__.py":
            continue
        for child in sorted(origin.parent.iterdir()):
            if child.is_dir() and child.name != "__pycache__" and not (child / "__init__.py").exists():
                rels.update(p.relative_to(source).as_posix() for p in _files(child))
    for rel in STATIC_FILES:
        rels.add(rel)
    for rel in STATIC_DIRS:
        rels.update(p.relative_to(source).as_posix() for p in _files(source / rel))
    return sorted(rels)


def check_bundle(bundle: Path) -> None:
    bundle = bundle.resolve()
    loaded = _load(bundle)
    outside = [name for name, origin in loaded.items() if not origin.is_relative_to(bundle)]
    if outside:
        raise SystemExit("bundle imported modules from outside itself: " + ", ".join(outside))
    if "preached.privacy" in loaded and not (loaded["preached.privacy"].parent / "privacy_data").is_dir():
        raise SystemExit("bundle is missing preached/privacy_data")
    import preached.libraries

    for slug in ("spurgeon", "edwards"):
        if not preached.libraries.is_public_domain(slug):
            raise SystemExit(f"bundle cannot load the {slug} manifest")


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("list", "check"):
        print("usage: bundle_files.py list SOURCE | check BUNDLE", file=sys.stderr)
        return 2
    root = Path(argv[2])
    if argv[1] == "list":
        for rel in list_files(root):
            print(rel)
    else:
        check_bundle(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
