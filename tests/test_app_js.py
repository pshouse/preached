"""app.js URL rules, run in Deno when it is installed (skipped otherwise; no new dependency)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "app.js"

PRELUDE = """
function FakeEl(tag) {
  this.tagName = String(tag).toUpperCase();
  this.className = "";
  this.textContent = "";
  this.children = [];
  this.attrs = {};
  this.href = "";
  this.target = "";
  this.rel = "";
  this.type = "";
}
FakeEl.prototype.appendChild = function (child) { this.children.push(child); return child; };
FakeEl.prototype.setAttribute = function (name, value) { this.attrs[name] = String(value); };
FakeEl.prototype.addEventListener = function () {};
globalThis.window = { location: { origin: "http://127.0.0.1:8000" } };
globalThis.document = {
  addEventListener() {},
  getElementById() { return null; },
  createElement(tag) { return new FakeEl(tag); },
  querySelector() { return null; },
  querySelectorAll() { return []; },
};
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
eq(PREROLL_S, 0.75, "pre-roll");
eq(playStart(32.81), 32.06, "pre-roll start");
eq(playStart(10), 9.25, "pre-roll whole");
eq(playStart(0.5), 0, "clamped at 0");
eq(playStart(0), 0, "zero");
eq(playStart(null), null, "no time");
eq(playStart(-3), null, "negative");
eq(playStart("abc"), null, "nan");
eq(playStart(NaN), null, "NaN");
eq(playStart(Infinity), null, "inf");
eq(playStart(-Infinity), null, "-inf");
eq(formatTime(32.81), "0:00:32", "label stays exact");

eq(youtubeWatchUrl("https://www.youtube.com/watch?v=abcdefghijk&t=11s"), "https://www.youtube.com/watch?v=abcdefghijk&t=11s", "stored www");
eq(youtubeWatchUrl("https://youtube.com/watch?v=abcdefghijk&t=0s"), "https://youtube.com/watch?v=abcdefghijk&t=0s", "apex host");
eq(youtubeWatchUrl("https://m.youtube.com/watch?v=abcdefghijk&t=3s"), "https://m.youtube.com/watch?v=abcdefghijk&t=3s", "mobile host");
eq(youtubeWatchUrl("https://WWW.YouTube.com/watch?v=abc_def-01X&t=11s"), "https://WWW.YouTube.com/watch?v=abc_def-01X&t=11s", "stored as-is");
eq(youtubeWatchUrl("https://www.youtube.com:443/watch?v=abcdefghijk&t=11s"), "https://www.youtube.com:443/watch?v=abcdefghijk&t=11s", "port 443");
eq(youtubeWatchUrl("https://www.youtube.com.evil.com/watch?v=abcdefghijk"), null, "evil suffix");
eq(youtubeWatchUrl("javascript:alert(1)"), null, "javascript");
eq(youtubeWatchUrl("http://www.youtube.com/watch?v=abcdefghijk"), null, "http youtube");
eq(youtubeWatchUrl("https://youtu.be/abcdefghijk"), null, "short link");
eq(youtubeWatchUrl("https://www.youtube.com/embed/abcdefghijk"), null, "embed");
eq(youtubeWatchUrl("https://www.youtube.com/watch?v=short"), null, "short id");
eq(youtubeWatchUrl("https://www.youtube.com/watch?v=abcdefghijkl"), null, "12 char id");
eq(youtubeWatchUrl("https://evil.com@www.youtube.com/watch?v=abcdefghijk"), null, "userinfo");
eq(youtubeWatchUrl("https://www.youtube.com:8443/watch?v=abcdefghijk"), null, "odd port");
eq(youtubeWatchUrl("https://www.youtube.com:abc/watch?v=abcdefghijk"), null, "non-numeric port");
eq(youtubeWatchUrl("https://www.youtube.com:99999/watch?v=abcdefghijk"), null, "port out of range");
eq(youtubeWatchUrl("https://[::1]/watch?v=abcdefghijk"), null, "ipv6 host");
eq(youtubeWatchUrl("https://[gggg::1]/watch?v=abcdefghijk"), null, "invalid ipv6");
eq(youtubeWatchUrl("https://archive.org/download/x/y.mp3"), null, "archive is not youtube");

function walk(node, out) {
  out.push(node);
  var kids = node.children || [];
  for (var i = 0; i < kids.length; i += 1) walk(kids[i], out);
  return out;
}
function playNodes(root, tag) {
  return walk(root, []).filter(function (node) {
    return node.tagName === tag && node.className === "play";
  });
}

var yt = renderCard({
  sermon_title: "On Mercy",
  text: "grace",
  start_s: 95,
  end_s: 110,
  audio_url: "https://www.youtube.com/watch?v=abcdefghijk&t=94s",
  source_url: "https://www.ccel.org/x",
});
var watch = playNodes(yt, "A");
eq(watch.length, 1, "one watch link");
eq(watch[0].textContent, "Watch on YouTube at 0:01:35", "watch label");
eq(watch[0].href, "https://www.youtube.com/watch?v=abcdefghijk&t=94s", "stored href");
eq(watch[0].target, "_blank", "new tab");
eq(watch[0].rel, "noopener noreferrer", "rel");
eq(watch[0].href.indexOf("#t="), -1, "no media fragment");
eq(playNodes(yt, "BUTTON").length, 0, "youtube has no player button");

var archive = renderCard({
  sermon_title: "Salvation by Faith",
  sermon_number: 1,
  text: "grace",
  start_s: 32.81,
  end_s: 40,
  audio_url: "https://archive.org/download/x/y.mp3",
  reader: "Reader",
  source_url: "https://www.ccel.org/x",
});
var buttons = playNodes(archive, "BUTTON");
eq(buttons.length, 1, "archive button");
eq(buttons[0].textContent, "Play from 0:00:32", "archive label");
eq(playNodes(archive, "A").length, 0, "archive is not a youtube link");

var evil = renderCard({
  sermon_title: "Nope",
  text: "x",
  start_s: 3,
  end_s: 4,
  audio_url: "https://www.youtube.com.evil.com/watch?v=abcdefghijk",
});
eq(playNodes(evil, "A").length, 0, "evil host is not a watch link");
eq(playNodes(evil, "BUTTON").length, 1, "evil host keeps the player button");

var scriptUrl = renderCard({
  sermon_title: "Nope",
  text: "x",
  start_s: 3,
  end_s: 4,
  audio_url: "javascript:alert(1)",
});
eq(playNodes(scriptUrl, "A").length, 0, "javascript is not a link");
eq(playNodes(scriptUrl, "BUTTON").length, 0, "javascript is not a player");

var mobile = renderCard({
  sermon_title: "Mobile",
  text: "x",
  start_s: 12.2,
  end_s: 20,
  audio_url: "https://m.youtube.com/watch?v=abcdefghijk&t=11s",
});
eq(playNodes(mobile, "A")[0].href, "https://m.youtube.com/watch?v=abcdefghijk&t=11s", "mobile href as stored");
eq(playNodes(mobile, "A")[0].textContent, "Watch on YouTube at 0:00:12", "mobile label");
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

    def test_seek_uses_the_preroll(self) -> None:
        source = APP_JS.read_text()
        self.assertIn("var seconds = playStart(start);", source)
        # The label is built from the exact start_s, not the pre-rolled one.
        self.assertIn("var startLabel = formatTime(hit.start_s);", source)


class PrerollParityTests(unittest.TestCase):
    def test_same_preroll_as_python(self) -> None:
        import re

        from preached.search import PREROLL_S

        match = re.search(r"var PREROLL_S = ([0-9.]+);", APP_JS.read_text())
        self.assertIsNotNone(match)
        self.assertEqual(float(match.group(1)), PREROLL_S)


if __name__ == "__main__":
    unittest.main()
