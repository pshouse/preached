"""scripts/parity_hash.py on a synthetic index: stable, pinned, documented.

The index is built by the side tests' builders and searched with the
fixture encoder (no model, no /cache). A change to any served response
moves these pins on purpose: re-run ``PinTests`` and re-pin ``PINNED`` and
``PINNED_NO_WHY`` with the new values only when the change is meant.
"""

from __future__ import annotations

__import__("importlib").import_module("tests.cache_guard" if __package__ else "cache_guard").install()

import json
import os
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scripts.parity_hash as parity_hash  # noqa: E402
from app.server import Searcher  # noqa: E402
from preached.store import connect  # noqa: E402
from test_side import FIXTURE_FP, build_library, classic_rows, encode_fixture  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INDEX_VERSION = "ab" * 32
PINNED = {
    "http": "76a5bfb9d9c51956",
    "no-church": "f8ae652ee227960c",
    "in-process": "2c4e3d735333a6b2",
    "in-process-no-health": "126e6bde69f9049a",
    "search+sermon": "8a7e7554637ecc80",
    "side": "3a734e17aff1638d",
    "church": "0783e6ef1d4a916b",
}
PINNED_NO_WHY = {
    "http": "c293e4922f8c7341",
    "no-church": "2e08417eed1908c8",
    "in-process": "ca73b0128ad41a55",
    "in-process-no-health": "b60551efd3fe0919",
    "search+sermon": "f2634f94688508d3",
    "side": "ec626163bcf2eadd",
    "church": "604f7b2ce0ee1218",
}


def fixture_loader(connection, _model_key):
    return Searcher(connection, model="fixture", fingerprint=FIXTURE_FP), encode_fixture


def run(*extra: str) -> tuple[int, str, str]:
    """One harness run on a newly built synthetic index."""
    with tempfile.TemporaryDirectory() as tmp:
        index = Path(tmp) / "wesley.sqlite"
        build_library(index, *classic_rows())
        with closing(connect(index)) as writer:
            writer.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('chunks_sha256', ?)", (INDEX_VERSION,))
            writer.commit()
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = parity_hash.main(["--index", str(index), *extra], loader=fixture_loader)
    return code, out.getvalue(), err.getvalue()


def hashes(stdout: str) -> dict[str, str]:
    lines = [line.split(" ") for line in stdout.splitlines()]
    return {name: value for name, value in lines}


class CanonicalTests(unittest.TestCase):
    def test_sorted_compact_utf8(self) -> None:
        self.assertEqual(
            parity_hash.canonical({"b": 1, "a": [1.5, "é", None, True]}),
            '{"a":[1.5,"é",null,true],"b":1}'.encode("utf-8"),
        )

    def test_nan_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            parity_hash.canonical(float("nan"))

    def test_strip_drops_keys_at_any_depth(self) -> None:
        value = {"took_ms": 3, "results": [{"why": {"x": 1}, "text": "a"}], "classic": {"why": 2, "k": 1}}
        self.assertEqual(
            parity_hash.strip(value, frozenset({"took_ms", "why"})),
            {"results": [{"text": "a"}], "classic": {"k": 1}},
        )

    def test_digest_is_sha256_prefix(self) -> None:
        import hashlib

        self.assertEqual(parity_hash.digest([1]), hashlib.sha256(b"[1]").hexdigest()[:16])


class PinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.saved = {name: os.environ.get(name) for name in (*parity_hash.RATE_ENV, *parity_hash.UNSET_ENV)}
        cls.first = run()
        cls.second = run()
        cls.no_why = run("--strip", "why")

    def test_two_runs_print_the_same_hashes(self) -> None:
        self.assertEqual(self.first[0], 0, self.first[2])
        self.assertEqual(self.first[1], self.second[1])
        self.assertEqual(list(hashes(self.first[1])), list(parity_hash.SETS))

    def test_pinned_synthetic_hashes(self) -> None:
        self.assertEqual(hashes(self.first[1]), PINNED)
        self.assertEqual(hashes(self.no_why[1]), PINNED_NO_WHY)

    def test_strip_why_moves_every_set(self) -> None:
        with_why, without = hashes(self.first[1]), hashes(self.no_why[1])
        for name in parity_hash.SETS:
            self.assertNotEqual(with_why[name], without[name], name)

    def test_stderr_names_index_model_and_harness(self) -> None:
        about = self.first[2].strip().splitlines()[-1]
        self.assertEqual(
            about,
            f"index_version={INDEX_VERSION} model_sha256=None "
            f"harness={parity_hash.harness_sha256(parity_hash.INPUTS)} strip=took_ms",
        )
        self.assertTrue(self.no_why[2].strip().endswith("strip=took_ms,why"))

    def test_environment_is_restored(self) -> None:
        now = {name: os.environ.get(name) for name in self.saved}
        self.assertEqual(now, self.saved)

    def test_expect_mismatch_exits_one(self) -> None:
        good = [f"--expect=http={PINNED['http']}", f"--expect=church={PINNED['church']}"]
        self.assertEqual(run(*good)[0], 0)
        code, _, err = run("--expect", "side=0000000000000000")
        self.assertEqual(code, 1)
        self.assertIn("MISMATCH side: got ", err)


class InputsTests(unittest.TestCase):
    def test_inputs_are_the_frozen_eval_queries_and_probes(self) -> None:
        inputs = json.loads(parity_hash.INPUTS.read_text(encoding="utf-8"))
        self.assertEqual(len(inputs["queries"]), 93)
        self.assertEqual(inputs["queries"][0]["id"], "q-worry")
        self.assertEqual(len({item["id"] for item in inputs["queries"]}), 93)
        self.assertNotIn("/healthz", inputs["probes"])
        self.assertEqual((inputs["k"], inputs["side_k"]), (10, 5))

    def test_doc_records_this_harness(self) -> None:
        doc = (ROOT / "docs" / "PARITY.md").read_text(encoding="utf-8")
        self.assertIn(f"`{parity_hash.harness_sha256(parity_hash.INPUTS)}`", doc)


if __name__ == "__main__":
    unittest.main()
