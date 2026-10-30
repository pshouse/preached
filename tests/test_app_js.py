"""app.js URL rules, run in Deno when it is installed (skipped otherwise; no new dependency)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"

PRELUDE = """
globalThis.window = { location: { origin: "http://127.0.0.1:8000" } };
globalThis.document = { addEventListener() {}, getElementById() { return null; } };
"""

CHECKS = """
function eq(actual, expected, label) {
  if (actual !== expected) throw new Error(label + ": got " + actual + ", want " + expected);
}
eq(safeUrl("https://archive.org/download/x/y.mp3"), "https://archive.org/download/x/y.mp3", "https");
eq(safeUrl("http://archive.org/download/x/y.mp3"), null, "remote http");
eq(safeUrl("javascript:alert(1)"), null, "javascript");
eq(safeUrl("data:audio/mp3;base64,AAAA"), null, "data");
eq(safeUrl("//evil.example/a.mp3"), null, "protocol-relative http page");
eq(safeUrl("/fixture/a.mp3"), "http://127.0.0.1:8000/fixture/a.mp3", "same origin");
eq(safeUrl(""), null, "empty");
eq(safeUrl(null), null, "null");
eq(mediaUrlAt("https://archive.org/a.mp3", 95), "https://archive.org/a.mp3#t=95", "plain");
eq(mediaUrlAt("https://archive.org/a.mp3#t=10", 95), "https://archive.org/a.mp3#t=95", "replace t");
eq(mediaUrlAt("https://archive.org/a.mp3?x=1#frag", 1.5), "https://archive.org/a.mp3?x=1#t=1.5", "replace other");
eq(mediaUrlAt("https://archive.org/a.mp3#keep", null), "https://archive.org/a.mp3#keep", "no time");
eq(mediaUrlAt("https://archive.org/a.mp3", -1), "https://archive.org/a.mp3", "negative");
console.log("ok");
"""


@unittest.skipUnless(shutil.which("deno"), "deno not installed")
class AppJsTests(unittest.TestCase):
    def test_url_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "check.js"
            script.write_text(PRELUDE + APP_JS.read_text() + CHECKS)
            result = subprocess.run(
                ["deno", "run", "--quiet", "--no-prompt", "--no-config", str(script)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_seek_uses_the_fragment_helper(self) -> None:
        source = APP_JS.read_text()
        self.assertIn("audio.src = mediaUrlAt(url, seconds);", source)
        self.assertNotIn('"#t="', source)


if __name__ == "__main__":
    unittest.main()
