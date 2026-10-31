"""Phone-page behaviour from the W3 mobile QA pass (reports/W3-MOBILE-UX-QA.md).

Static checks read index.html, app.css and app.js. Behaviour checks run
app.js in Deno against a fake DOM (skipped when Deno is not installed).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
APP_JS = STATIC / "app.js"
INDEX = STATIC / "index.html"
CSS = STATIC / "app.css"
SERVER = STATIC.parent / "server.py"


class _Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.stack: list[str] = []
        self.parents: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        self.tags.append((tag, found))
        if found.get("id"):
            self.parents[found["id"]] = list(self.stack)
        if tag not in ("meta", "link", "input", "br", "img"):
            self.stack.append(found.get("id") or found.get("class") or tag)

    def handle_endtag(self, tag: str) -> None:
        if self.stack:
            self.stack.pop()

    def by_id(self, ident: str) -> tuple[str, dict[str, str | None]]:
        for tag, attrs in self.tags:
            if attrs.get("id") == ident:
                return tag, attrs
        raise AssertionError(f"no #{ident}")


def parse_page() -> _Tags:
    parser = _Tags()
    parser.feed(INDEX.read_text())
    return parser


def css_block(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    if match is None:
        raise AssertionError(f"no CSS rule {selector}")
    return match.group(1)


class PhonePageStaticTests(unittest.TestCase):
    def test_viewport_allows_zoom(self) -> None:
        page = parse_page()
        viewport = [a for t, a in page.tags if t == "meta" and a.get("name") == "viewport"]
        self.assertEqual(len(viewport), 1)
        content = viewport[0]["content"] or ""
        self.assertIn("width=device-width", content)
        self.assertIn("initial-scale=1", content)
        # Pinch zoom must stay available for readers who need it.
        self.assertNotIn("user-scalable", content)
        self.assertNotIn("maximum-scale", content)

    def test_every_control_has_a_label(self) -> None:
        page = parse_page()
        labelled = {a.get("for") for t, a in page.tags if t == "label"}
        for ident in ("q", "mode", "view"):
            self.assertIn(ident, labelled)
        _, query = page.by_id("q")
        self.assertEqual(query.get("type"), "search")
        self.assertEqual(query.get("enterkeyhint"), "search")
        self.assertIn("required", query)
        self.assertEqual(page.by_id("search-form")[1].get("role"), "search")
        self.assertIn("controls", page.by_id("player")[1])

    def test_confidence_banner_is_announced(self) -> None:
        # The low-confidence banner and fallback note sit in a polite live
        # region, so a screen reader hears them, not only "10 passages."
        page = parse_page()
        self.assertIn("notices", page.parents["confidence"])
        self.assertIn("notices", page.parents["note"])
        self.assertNotIn("status", page.parents["confidence"])  # no nested live regions
        html = INDEX.read_text()
        self.assertIn('<div class="notices" aria-live="polite">', html)
        self.assertIn('role="status" aria-live="polite"', html)

    def test_player_bar_starts_hidden(self) -> None:
        _, bar = parse_page().by_id("player-bar")
        self.assertIn("hidden", bar)
        self.assertIn('document.getElementById("player-bar")', APP_JS.read_text())

    def test_tap_targets_and_text_size(self) -> None:
        css = CSS.read_text()
        for selector in (".card .text-link a", ".card a.play", ".skip", "button"):
            self.assertIn("min-height: 44px", css_block(css, selector), selector)
        # 16px inputs: iOS Safari zooms the page on focus below that.
        self.assertIn("font-size: 1rem", css_block(css, 'select'))
        self.assertIn("scroll-margin-top", css_block(css, ".results-section"))

    def test_query_limit_matches_server(self) -> None:
        _, query = parse_page().by_id("q")
        match = re.search(r"var MAX_QUERY = (\d+);", APP_JS.read_text())
        self.assertIsNotNone(match)
        self.assertEqual(query.get("maxlength"), match.group(1))
        self.assertIn(f"len(query) > {match.group(1)}", SERVER.read_text())

    def test_copy_does_not_speak_for_the_preacher(self) -> None:
        html = INDEX.read_text()
        self.assertIn("it never writes or paraphrases", html)
        script = APP_JS.read_text()
        for phrase in ("Wesley would", "Wesley says you", "In summary", "answer:", "Answer:"):
            self.assertNotIn(phrase, html)
            self.assertNotIn(phrase, script)


FAKE = r"""
function FakeNode(tag) {
  this.tagName = tag; this.children = []; this.textContent = ""; this.hidden = false;
  this.attrs = {}; this.dataset = {}; this.className = ""; this.listeners = {};
  this.href = ""; this.type = ""; this.rel = ""; this.target = "";
  this.scrolled = null; this.top = 0;
  var classes = new Set();
  this.classList = {
    add: function (c) { classes.add(c); }, remove: function (c) { classes.delete(c); },
    contains: function (c) { return classes.has(c); },
    toggle: function (c, on) { if (on) classes.add(c); else classes.delete(c); },
  };
}
FakeNode.prototype.appendChild = function (n) { this.children.push(n); return n; };
FakeNode.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
FakeNode.prototype.addEventListener = function (k, f) { this.listeners[k] = f; };
FakeNode.prototype.getBoundingClientRect = function () { return { top: this.top }; };
FakeNode.prototype.scrollIntoView = function (opts) { this.scrolled = opts; };
var nodes = {};
["results-section", "player-bar", "now-playing"].forEach(function (id) { nodes[id] = new FakeNode("x"); });
nodes["player-bar"].hidden = true;
var audio = new FakeNode("audio");
audio.readyState = 0; audio.currentTime = 0;
audio.load = function () {};
audio.play = function () { return Promise.reject(new Error("held")); };
nodes.player = audio;
globalThis.window = { location: { origin: "http://127.0.0.1:8000" }, innerHeight: 812 };
globalThis.document = {
  addEventListener() {},
  getElementById(id) { return nodes[id] || null; },
  createElement(tag) { return new FakeNode(tag); },
  querySelector() { return null; },
  querySelectorAll() { return []; },
};
"""

CHECKS = r"""
function eq(actual, expected, label) {
  if (actual !== expected) throw new Error(label + ": got " + JSON.stringify(actual) + ", want " + JSON.stringify(expected));
}
function walk(node, out) {
  out.push(node);
  (node.children || []).forEach(function (child) { walk(child, out); });
  return out;
}
function text(node) { return walk(node, []).map(function (n) { return n.textContent || ""; }).join("\n"); }

var base = {
  sermon_title: "Wandering Thoughts", sermon_number: 41, sermon_id: "wesley-041",
  text: "Thoughts that wander from God.", start_s: 92.02, end_s: 145.3,
  audio_url: "https://archive.org/download/x/y.mp3", reader: "Reader",
  source_url: "https://ccel.org/ccel/wesley/sermons/sermons.v.xli.html",
};

// Rule 2: a timed card names the sermon and shows the time it plays from.
var card = renderCard(base);
var all = walk(card, []);
eq(all.filter(function (n) { return n.tagName === "h3"; })[0].textContent, "Wandering Thoughts", "title");
eq(all.filter(function (n) { return n.className === "timing"; })[0].textContent, "0:01:32–0:02:25", "range");
var play = all.filter(function (n) { return n.className === "play"; });
eq(play.length, 1, "one play control");
eq(play[0].attrs["aria-label"], "Play sermon 41 from 0:01:32", "spoken label");

// Privacy: a withheld (flagged) passage has no play control, no link to the
// recording and no times, even if the hit still carries an audio_url.
var flagged = Object.assign({}, base, { audio_withheld: true });
var flaggedCard = renderCard(flagged);
var flaggedNodes = walk(flaggedCard, []);
eq(flaggedNodes.filter(function (n) { return n.className === "play"; }).length, 0, "flagged: no play");
eq(flaggedNodes.filter(function (n) { return n.tagName === "button"; }).length, 0, "flagged: no button");
eq(flaggedNodes.filter(function (n) { return n.tagName === "a" && n.href.indexOf("archive.org") !== -1; }).length, 0,
   "flagged: no recording link");
eq(text(flaggedCard).indexOf("0:01:32"), -1, "flagged: no time");
eq(text(flaggedCard).indexOf("audio is withheld") >= 0, true, "flagged: says why");
eq(text(flaggedCard).indexOf("Wandering Thoughts") >= 0, true, "flagged: still names the sermon");
var flaggedYoutube = Object.assign({}, flagged, { audio_url: "https://www.youtube.com/watch?v=samplevid01&t=11s" });
eq(walk(renderCard(flaggedYoutube), []).filter(function (n) { return n.tagName === "a" && n.href.indexOf("youtube") !== -1; }).length,
   0, "flagged: no watch link");

// A watch link says it opens a new tab.
var yt = walk(renderCard(Object.assign({}, base, { audio_url: "https://www.youtube.com/watch?v=samplevid01&t=11s" })), [])
  .filter(function (n) { return n.className === "play"; })[0];
eq(yt.target, "_blank", "watch opens a tab");
eq(yt.attrs["aria-label"], "Watch on YouTube at 0:01:32 (opens in a new tab)", "watch label");

// The player bar is hidden until the first Play, then shown.
eq(nodes["player-bar"].hidden, true, "bar hidden at load");
playClip("https://archive.org/download/x/y.mp3", 92.02, play[0], "Wandering Thoughts · 0:01:32");
eq(nodes["player-bar"].hidden, false, "bar shown on play");
eq(audio.dataset.seek, "91.27", "seek with pre-roll");

// Results scroll into view only when they start off screen.
nodes["results-section"].top = 900;
revealResults();
eq(nodes["results-section"].scrolled && nodes["results-section"].scrolled.block, "start", "scrolls when below the fold");
nodes["results-section"].scrolled = null;
nodes["results-section"].top = 200;
revealResults();
eq(nodes["results-section"].scrolled, null, "no scroll when already on screen");

eq(MESSAGES.network.indexOf("connection") >= 0, true, "network copy");
eq(MESSAGES.enter, "Enter a question.", "empty copy");

// Held-audio caption reads as two sentences.
setTimeout(function () {
  eq(nodes["now-playing"].textContent,
     "Wandering Thoughts · 0:01:32. Press play on the bar if the browser held the audio.", "held caption");
  console.log("ok");
}, 0);
"""


@unittest.skipUnless(shutil.which("deno"), "deno not installed")
class PhonePageBehaviourTests(unittest.TestCase):
    def test_cards_player_and_scroll(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "check.js"
            script.write_text(FAKE + APP_JS.read_text() + CHECKS)
            result = subprocess.run(
                ["deno", "run", "--quiet", "--no-prompt", "--no-config", str(script)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
