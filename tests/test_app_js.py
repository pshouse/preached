"""app.js URL rules, run in Deno when it is installed (skipped otherwise; no new dependency)."""

from __future__ import annotations

import re
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
eq(youtubeWatchUrl("https://youtube.com/watch?v=abcdefghijk&t=0s"), "https://www.youtube.com/watch?v=abcdefghijk&t=0s", "apex host rebuilt");
eq(youtubeWatchUrl("https://m.youtube.com/watch?v=abcdefghijk&t=3s"), "https://www.youtube.com/watch?v=abcdefghijk&t=3s", "mobile host rebuilt");
eq(youtubeWatchUrl("https://WWW.YouTube.com/watch?v=abc_def-01X&t=11s"), "https://www.youtube.com/watch?v=abc_def-01X&t=11s", "mixed case rebuilt");
eq(youtubeWatchUrl("https://www.youtube.com:443/watch?v=abcdefghijk&t=11s"), "https://www.youtube.com/watch?v=abcdefghijk&t=11s", "port 443 rebuilt");
eq(youtubeWatchUrl("https://www.youtube.com/watch?v=abcdefghijk&t=11s#keep"), "https://www.youtube.com/watch?v=abcdefghijk&t=11s", "fragment dropped");
eq(youtubeWatchUrl("https://www.youtube.com/watch?v=abcdefghijk&t=javascript:alert(1)"), "https://www.youtube.com/watch?v=abcdefghijk", "hostile t dropped");
eq(youtubeWatchUrl("https://www.youtube.com/watch?v=abcdefghijk&t=11s&redirect=https://evil.example"), "https://www.youtube.com/watch?v=abcdefghijk&t=11s", "extra param dropped");
eq(youtubeWatchUrl("https://www.youtube.com/watch?v=abcdefghijk&t=86401s"), "https://www.youtube.com/watch?v=abcdefghijk", "t over 24h dropped");
eq(youtubeWatchUrl("https://www.youtube.com/watch?v=abcdefghijk&t=86400"), "https://www.youtube.com/watch?v=abcdefghijk&t=86400s", "24h kept");
eq(youtubeWatchUrl("https://www.youtube.com/watch?v=abcdefghijk&v="), null, "blank second v");
eq(youtubeWatchUrl("https://www.youtube.com/watch?v=&v=abcdefghijk"), null, "blank first v");
eq(youtubeWatchUrl("https://www.youtube.com/watch?v=abcdefghijk&v"), null, "bare second v");
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
function textLinks(root) {
  return walk(root, []).filter(function (node) {
    return node.tagName === "A" && node.className !== "play";
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
eq(playNodes(mobile, "A")[0].href, "https://www.youtube.com/watch?v=abcdefghijk&t=11s", "mobile href rebuilt");
eq(playNodes(mobile, "A")[0].textContent, "Watch on YouTube at 0:00:12", "mobile label");

eq(textLinks(yt).length, 1, "ccel source stays beside a youtube watch link");
eq(textLinks(yt)[0].textContent, "Read this sermon on CCEL", "ccel label");
eq(textLinks(yt)[0].href, "https://www.ccel.org/x", "ccel href");
eq(textLinks(yt)[0].rel, "noreferrer", "source rel");
eq(textLinks(archive)[0].textContent, "Read this sermon on CCEL", "archive card ccel label");

var duplicate = renderCard({
  sermon_title: "On Mercy",
  text: "grace",
  start_s: 95,
  end_s: 110,
  audio_url: "https://www.youtube.com/watch?v=abcdefghijk&t=94s",
  source_url: "https://m.youtube.com/watch?v=abcdefghijk",
});
eq(textLinks(duplicate).length, 0, "same video is not a second source link");
eq(playNodes(duplicate, "A").length, 1, "watch link remains");

var otherVideo = renderCard({
  sermon_title: "On Mercy",
  text: "grace",
  start_s: 95,
  end_s: 110,
  audio_url: "https://www.youtube.com/watch?v=abcdefghijk&t=94s",
  source_url: "https://www.youtube.com/watch?v=zzzzzzzzzzz",
});
eq(textLinks(otherVideo).length, 1, "different video is a source");
eq(textLinks(otherVideo)[0].textContent, "Watch the source on YouTube", "youtube source label");
eq(textLinks(otherVideo)[0].href, "https://www.youtube.com/watch?v=zzzzzzzzzzz", "source rebuilt");

var hostileSource = renderCard({
  sermon_title: "On Mercy",
  text: "grace",
  start_s: 95,
  end_s: 110,
  audio_url: "https://www.youtube.com/watch?v=abcdefghijk&t=javascript:alert(1)&redirect=https://evil.example",
  source_url: "https://www.youtube.com/watch?v=zzzzzzzzzzz&t=javascript:alert(1)&redirect=https://evil.example",
});
eq(playNodes(hostileSource, "A")[0].href, "https://www.youtube.com/watch?v=abcdefghijk", "watch drops hostile t");
eq(playNodes(hostileSource, "A")[0].href.indexOf("javascript"), -1, "watch href has no javascript");
eq(playNodes(hostileSource, "A")[0].href.indexOf("redirect"), -1, "watch href has no redirect");
eq(textLinks(hostileSource)[0].href, "https://www.youtube.com/watch?v=zzzzzzzzzzz", "source drops hostile t");
eq(textLinks(hostileSource)[0].href.indexOf("redirect"), -1, "source href has no redirect");

var plain = renderCard({
  sermon_title: "Other",
  text: "x",
  start_s: null,
  source_url: "https://example.com/text",
});
eq(textLinks(plain).length, 1, "other https source");
eq(textLinks(plain)[0].textContent, "Source", "not labeled ccel");
eq(textLinks(plain)[0].textContent.indexOf("CCEL"), -1, "no ccel word");

var lookalike = renderCard({
  sermon_title: "Other",
  text: "x",
  start_s: null,
  source_url: "https://ccel.org.evil.com/x",
});
eq(textLinks(lookalike)[0].textContent, "Source", "lookalike host is not ccel");

var apexCcel = renderCard({
  sermon_title: "Wesley",
  text: "x",
  start_s: null,
  source_url: "https://ccel.org/ccel/wesley/sermons/sermons.v.i.html",
});
eq(textLinks(apexCcel)[0].textContent, "Read this sermon on CCEL", "apex ccel");

var scriptSource = renderCard({
  sermon_title: "Other",
  text: "x",
  start_s: null,
  source_url: "javascript:alert(1)",
});
eq(textLinks(scriptSource).length, 0, "javascript source is not a link");

var httpSource = renderCard({
  sermon_title: "Other",
  text: "x",
  start_s: null,
  source_url: "http://ccel.org/ccel/wesley/sermons/sermons.v.i.html",
});
eq(textLinks(httpSource).length, 0, "http source is not a link");
console.log("ok");
"""


STATE_CHECKS = """
function eq(actual, expected, label) {
  if (actual !== expected) throw new Error(label + ": got " + JSON.stringify(actual) + ", want " + JSON.stringify(expected));
}
var hits = [{ sermon_title: "A" }, { sermon_title: "B" }];
var s = describeResponse({ results: hits, note: null, abstain: false, confidence: { level: "strong", note: null } });
eq(s.kind, "results", "strong kind"); eq(s.status, "2 passages.", "count"); eq(s.confidenceNote, null, "no note");
s = describeResponse({ results: hits, abstain: false, confidence: { level: "weak", note: "Server weak note." } });
eq(s.kind, "weak", "weak kind"); eq(s.confidenceNote, "Server weak note.", "server note wins"); eq(s.showResults, true, "weak shows");
s = describeResponse({ results: hits, abstain: false, confidence: { level: "weak" } });
eq(s.confidenceNote, MESSAGES.weak, "default weak note");
// Low confidence (abstain): shown by default under a banner that calls the check a heuristic.
s = describeResponse({ results: hits, abstain: true, confidence: { level: "none", note: "x" } });
eq(s.kind, "low", "low kind"); eq(s.showResults, true, "low shows by default"); eq(s.canHide, true, "can hide");
eq(s.status, "2 passages.", "low count"); eq(s.confidenceNote, MESSAGES.low, "low banner");
eq(MESSAGES.low.indexOf("heuristic") >= 0, true, "banner says heuristic");
s = describeResponse({ results: hits, abstain: true, confidence: { level: "none" } }, true);
eq(s.showResults, false, "toggle hides"); eq(s.status, MESSAGES.lowHidden, "hidden copy");
s = describeResponse({ results: hits, abstain: false, confidence: { level: "strong" } }, true);
eq(s.showResults, true, "toggle leaves strong results"); eq(s.canHide, false, "no toggle on strong");
s = describeResponse({ results: [], abstain: true, confidence: { level: "none" } });
eq(s.kind, "empty", "empty kind"); eq(s.canHide, false, "nothing to hide");
eq(s.status.indexOf("Nothing found in these sermons."), 0, "empty copy");
s = describeResponse({ results: hits, note: "Embedding model failed to load; results are BM25 only.", confidence: { level: "unrated" } });
eq(s.kind, "results", "unrated shows"); eq(s.fallbackNote, "Embedding model failed to load; results are BM25 only.", "fallback note");
s = describeResponse({ results: hits });
eq(s.kind, "results", "older server without confidence");
s = describeResponse(null);
eq(s.kind, "empty", "null body");
eq(failureMessage("network"), MESSAGES.network, "network");
eq(failureMessage("http", 500, { error: "internal error" }), MESSAGES.server, "500 hides detail");
eq(failureMessage("http", 503, null), MESSAGES.server, "503");
eq(failureMessage("http", 400, { error: "q must be 1 to 300 characters" }), "Search failed: q must be 1 to 300 characters.", "400");
eq(failureMessage("garbled", 200, null), MESSAGES.garbled, "garbled");
console.log("ok");
"""

# A minimal DOM: enough for showResults, toggleLowConfidence, showFailure and
# renderCard to run for real. Nodes record textContent, hidden and classes.
FAKE_DOM = """
function FakeNode(tag) {
  this.tagName = tag; this.children = []; this.textContent = ""; this.hidden = false;
  this.attrs = {}; this.dataset = {}; this.focused = false; this.listeners = {};
  var classes = new Set();
  this.classList = {
    add: function (c) { classes.add(c); }, remove: function (c) { classes.delete(c); },
    contains: function (c) { return classes.has(c); },
    toggle: function (c, on) { if (on) classes.add(c); else classes.delete(c); },
  };
}
FakeNode.prototype.appendChild = function (n) { this.children.push(n); return n; };
FakeNode.prototype.replaceChildren = function () { this.children = []; };
FakeNode.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
FakeNode.prototype.getAttribute = function (k) { return this.attrs[k]; };
FakeNode.prototype.addEventListener = function (k, f) { this.listeners[k] = f; };
FakeNode.prototype.focus = function () { this.focused = true; };
Object.defineProperty(FakeNode.prototype, "innerHTML", { set: function () { throw new Error("innerHTML used"); } });
var nodes = {};
["results-section", "results", "note", "status", "confidence", "hide-low", "retry"].forEach(function (id) {
  nodes[id] = new FakeNode("x");
});
nodes.note.hidden = true; nodes.confidence.hidden = true; nodes["hide-low"].hidden = true; nodes.retry.hidden = true;
globalThis.window = { location: { origin: "http://127.0.0.1:8000" } };
globalThis.document = {
  addEventListener() {},
  getElementById(id) { return nodes[id] || null; },
  createElement(tag) { return new FakeNode(tag); },
  querySelector() { return null; },
};
"""

DOM_CHECKS = """
function eq(actual, expected, label) {
  if (actual !== expected) throw new Error(label + ": got " + JSON.stringify(actual) + ", want " + JSON.stringify(expected));
}
var hit = { sermon_title: "<b>Title</b>", text: "<img src=x onerror=alert(1)>", sermon_number: 5, start_s: null };
var abstained = { results: [hit, hit], note: null, abstain: true, confidence: { level: "none", note: "n" } };

lastSearch = "q";
setBusy(true);
eq(nodes["results-section"].attrs["aria-busy"], "true", "busy while loading");
showResults(abstained);
eq(nodes["results-section"].attrs["aria-busy"], "false", "not busy after");
eq(nodes.results.children.length, 2, "low-confidence results shown by default");
eq(nodes.confidence.hidden, false, "low banner shown");
eq(nodes.confidence.textContent, MESSAGES.low, "low banner text");
eq(nodes["hide-low"].hidden, false, "toggle offered");
eq(nodes["hide-low"].attrs["aria-pressed"], "false", "toggle off");
eq(nodes.status.textContent, "2 passages.", "low status");
toggleLowConfidence();
eq(nodes.results.children.length, 0, "toggle hides");
eq(nodes.confidence.hidden, true, "banner hidden with the results");
eq(nodes.status.textContent, MESSAGES.lowHidden, "hidden status");
eq(nodes["hide-low"].attrs["aria-pressed"], "true", "toggle on");
eq(nodes["hide-low"].hidden, false, "toggle stays");
eq(nodes["hide-low"].focused, true, "focus stays on the toggle");
showResults(abstained);
eq(nodes.results.children.length, 0, "choice holds for the next search");
toggleLowConfidence();
eq(nodes.results.children.length, 2, "toggle shows again");
var title = nodes.results.children[0].children[0].children[1];
eq(title.textContent, "<b>Title</b>", "title is text, not markup");

showResults({ results: [hit], note: "Embedding model failed to load; results are BM25 only.", abstain: false,
              confidence: { level: "unrated" } });
eq(nodes.note.hidden, false, "fallback note shown");
eq(nodes.note.textContent, "Embedding model failed to load; results are BM25 only.", "fallback text");
eq(nodes.confidence.hidden, true, "no weak note");
eq(nodes["hide-low"].hidden, true, "no toggle");
eq(nodes.status.textContent, "1 passage.", "count");

showResults({ results: [hit], abstain: false, confidence: { level: "weak", note: "Weak." } });
eq(nodes.confidence.textContent, "Weak.", "weak note");
eq(nodes.results.children.length, 1, "weak shows results");

showFailure(failureMessage("http", 500, { error: "internal error" }));
eq(nodes.status.textContent, MESSAGES.server, "500 copy");
eq(nodes.status.classList.contains("is-error"), true, "error style");
eq(nodes.retry.hidden, false, "retry offered");
eq(nodes.results.children.length, 0, "error clears results");
eq(nodes.note.hidden, true, "error clears note");

showResults({ results: [], abstain: true, confidence: { level: "none" } });
eq(nodes.status.classList.contains("is-error"), false, "error style cleared");
eq(nodes.retry.hidden, true, "retry hidden again");
eq(nodes["hide-low"].hidden, true, "nothing to hide");
console.log("ok");
"""


def run_deno(source: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "check.js"
        script.write_text(source)
        return subprocess.run(
            ["deno", "run", "--quiet", "--no-prompt", "--no-config", str(script)],
            capture_output=True,
            text=True,
            timeout=60,
        )


@unittest.skipUnless(shutil.which("deno"), "deno not installed")
class PageStateTests(unittest.TestCase):
    def test_describe_response_and_failures(self) -> None:
        result = run_deno(PRELUDE + APP_JS.read_text() + STATE_CHECKS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_states_in_a_fake_dom(self) -> None:
        result = run_deno(FAKE_DOM + APP_JS.read_text() + DOM_CHECKS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


class PageStaticTests(unittest.TestCase):
    def test_state_elements_and_no_inline_code(self) -> None:
        page = (APP_JS.parent / "index.html").read_text()
        script = APP_JS.read_text()
        for element in ('id="results-section"', 'aria-busy="false"', 'id="confidence"', 'id="hide-low"',
                        'id="retry"', 'role="status" aria-live="polite"'):
            self.assertIn(element, page)
        self.assertNotIn("style=", page)
        self.assertIsNone(re.search(r"<[^>]*\son[a-z]+\s*=", page))  # no inline event handlers
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "new Function", "document.write",
                       ".style."):
            self.assertNotIn(banned, script)


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
