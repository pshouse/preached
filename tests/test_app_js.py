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
eq(PREROLL_S, 0.75, "pre-roll");
eq(playStart(32.81), 32.06, "pre-roll start");
eq(playStart(10), 9.25, "pre-roll whole");
eq(playStart(0.5), 0, "clamped at 0");
eq(playStart(0), 0, "zero");
eq(playStart(null), null, "no time");
eq(playStart(-3), null, "negative");
eq(playStart("abc"), null, "nan");
eq(formatTime(32.81), "0:00:32", "label stays exact");
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
s = describeResponse({ results: hits, abstain: true, confidence: { level: "none", note: "x" } });
eq(s.kind, "abstain", "abstain kind"); eq(s.showResults, false, "abstain hides"); eq(s.canReveal, true, "can reveal");
eq(s.status.indexOf("Nothing strong found in these sermons."), 0, "abstain copy");
s = describeResponse({ results: [], abstain: true, confidence: { level: "none" } });
eq(s.kind, "empty", "empty kind"); eq(s.canReveal, false, "nothing to reveal");
eq(s.status.indexOf("Nothing strong found in these sermons."), 0, "empty copy");
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

# A minimal DOM: enough for showResults, revealClosest, showFailure and
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
["results-section", "results", "note", "status", "confidence", "reveal", "retry"].forEach(function (id) {
  nodes[id] = new FakeNode("x");
});
nodes.note.hidden = true; nodes.confidence.hidden = true; nodes.reveal.hidden = true; nodes.retry.hidden = true;
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
eq(nodes.results.children.length, 0, "abstain hides results");
eq(nodes.reveal.hidden, false, "reveal offered");
eq(nodes.status.textContent.indexOf("Nothing strong found in these sermons."), 0, "abstain status");
revealClosest();
eq(nodes.results.children.length, 2, "revealed");
eq(nodes.reveal.hidden, true, "reveal gone");
eq(nodes.confidence.hidden, false, "weak note shown with revealed results");
eq(nodes.confidence.focused, true, "focus moved to the note");
eq(nodes.status.textContent, "Showing the 2 closest passages anyway.", "reveal status");
var title = nodes.results.children[0].children[0].children[1];
eq(title.textContent, "<b>Title</b>", "title is text, not markup");

showResults({ results: [hit], note: "Embedding model failed to load; results are BM25 only.", abstain: false,
              confidence: { level: "unrated" } });
eq(nodes.note.hidden, false, "fallback note shown");
eq(nodes.note.textContent, "Embedding model failed to load; results are BM25 only.", "fallback text");
eq(nodes.confidence.hidden, true, "no weak note");
eq(nodes.reveal.hidden, true, "no reveal");
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
eq(nodes.reveal.hidden, true, "nothing to reveal");
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
        for element in ('id="results-section"', 'aria-busy="false"', 'id="confidence"', 'id="reveal"',
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
