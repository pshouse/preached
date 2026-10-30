"use strict";

/* Result text is untrusted. Put it in the page with textContent only. */

var playToken = 0;
var searchAbort = null;

function el(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function formatTime(seconds) {
  var value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return null;
  var total = Math.floor(value);
  var hours = Math.floor(total / 3600);
  var minutes = Math.floor((total % 3600) / 60);
  var secs = total % 60;
  return hours + ":" + String(minutes).padStart(2, "0") + ":" + String(secs).padStart(2, "0");
}

/* Same rule as the CSP: https anywhere, or this page's own origin. */
function safeUrl(value) {
  if (typeof value !== "string" || value === "") return null;
  try {
    var url = new URL(value, window.location.origin);
  } catch (err) {
    return null;
  }
  if (url.protocol === "https:") return url.href;
  if (url.origin === window.location.origin) return url.href;
  return null;
}

/* Player pre-roll: start_s is the exact onset of the passage's first word,
   and the label shows it. The player seeks this much earlier so a slightly
   late alignment never clips the first word. Same value as
   preached.search.PREROLL_S. */
var PREROLL_S = 0.75;

function playStart(start) {
  if (start == null || start === "") return null;
  var value = Number(start);
  if (!Number.isFinite(value) || value < 0) return null;
  return Math.max(0, Math.round((value - PREROLL_S) * 100) / 100);
}

/* Media fragment for a start time. Replaces any fragment the URL already has. */
function mediaUrlAt(href, seconds) {
  if (seconds == null || seconds === "") return href;
  var value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return href;
  var url = new URL(href);
  url.hash = "t=" + value;
  return url.href;
}

function isArchiveHost(href) {
  try {
    var host = new URL(href).hostname.toLowerCase();
  } catch (err) {
    return false;
  }
  return host === "archive.org" || host.endsWith(".archive.org");
}

/* Importer hosts that serve /watch?v=. youtu.be is a short link, not this form. */
var YOUTUBE_WATCH_HOSTS = { "youtube.com": 1, "www.youtube.com": 1, "m.youtube.com": 1 };
var YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;

/* Valid https watch URL, or null. Returns the stored string so &t= stays put.
   Does not add #t=. Host check matches the importer (no credentials, port 443
   or default). media-src does not allow YouTube, so callers must not put
   this URL on an <audio> element. */
function youtubeWatchUrl(value) {
  if (typeof value !== "string" || value === "") return null;
  if (value.charAt(0) === "-" || value.indexOf("\\") !== -1) return null;
  var i;
  for (i = 0; i < value.length; i += 1) {
    var code = value.charCodeAt(i);
    if (code <= 32 || code === 127) return null;
  }
  var url;
  try {
    url = new URL(value);
  } catch (err) {
    return null;
  }
  if (url.protocol !== "https:") return null;
  if (!YOUTUBE_WATCH_HOSTS[url.hostname]) return null;
  if (url.username || url.password) return null;
  if (url.port !== "" && url.port !== "443") return null;
  if (url.pathname !== "/watch") return null;
  var ids = url.searchParams.getAll("v");
  if (ids.length !== 1 || !YOUTUBE_ID.test(ids[0])) return null;
  return value;
}

/* CCEL only when the host is ccel.org. A YouTube source that is the same
   video as the watch link is not shown again. Anything else keeps a plain
   label. safeUrl still runs first; this does not accept a new scheme. */
function sourceLinkFor(sourceUrl, watchHref) {
  var source = safeUrl(sourceUrl);
  if (!source) return null;
  var host;
  try {
    host = new URL(source).hostname.toLowerCase();
  } catch (err) {
    return null;
  }
  if (host === "ccel.org" || host.endsWith(".ccel.org")) {
    return { href: source, text: "Read this sermon on CCEL" };
  }
  var youtube = youtubeWatchUrl(sourceUrl);
  if (youtube) {
    if (watchHref && sameYoutubeVideo(youtube, watchHref)) return null;
    return { href: youtube, text: "Watch the source on YouTube" };
  }
  /* A watch host that failed the watch rules is not forwarded as a link. */
  if (YOUTUBE_WATCH_HOSTS[host]) return null;
  return { href: source, text: "Source" };
}

function sameYoutubeVideo(a, b) {
  try {
    return new URL(a).searchParams.get("v") === new URL(b).searchParams.get("v");
  } catch (err) {
    return false;
  }
}

function readerLabel(hit, href) {
  var name = typeof hit.reader === "string" ? hit.reader : "";
  var librivox = href ? isArchiveHost(href) : false;
  if (name && librivox) return "Read by " + name + " (LibriVox volunteer)";
  if (name) return "Read by " + name;
  if (librivox) return "Read by a LibriVox volunteer";
  return "";
}

function seekWhenReady(audio) {
  if (!audio.dataset.seek) return;
  var target = Number(audio.dataset.seek);
  if (!Number.isFinite(target) || audio.readyState < 1) return;
  if (Math.abs(audio.currentTime - target) < 0.35) return;
  try {
    audio.currentTime = target;
  } catch (err) {
    /* The browser may not have a seekable range yet. A later event retries. */
  }
}

function playClip(url, start, button, caption) {
  var audio = document.getElementById("player");
  var token = ++playToken;
  var seconds = playStart(start);
  audio.dataset.token = String(token);
  audio.dataset.seek = seconds == null ? "" : String(seconds);
  if (audio.dataset.srcUrl !== url) {
    audio.dataset.srcUrl = url;
    audio.src = mediaUrlAt(url, seconds);
    audio.load();
  }
  seekWhenReady(audio);
  /* play() stays in the click so the browser treats it as a user gesture. */
  audio.play().catch(function () {
    if (Number(audio.dataset.token) !== token) return;
    document.getElementById("now-playing").textContent =
      caption + " Press play on the bar if the browser held the audio.";
  });
  var playing = document.querySelector(".play.is-playing");
  if (playing) playing.classList.remove("is-playing");
  button.classList.add("is-playing");
  document.getElementById("now-playing").textContent = caption;
}

function renderCard(hit) {
  var item = document.createElement("li");
  var card = el("article", "card");
  item.appendChild(card);

  var kickerBits = [];
  if (hit.sermon_number != null) kickerBits.push("Sermon " + hit.sermon_number);
  if (hit.sermon_id) kickerBits.push(String(hit.sermon_id));
  card.appendChild(el("p", "kicker", kickerBits.join(" · ") || "Sermon"));

  card.appendChild(el("h3", null, hit.sermon_title || "Untitled sermon"));
  if (hit.scripture) card.appendChild(el("p", "scripture", hit.scripture));

  var quote = document.createElement("blockquote");
  quote.appendChild(el("p", null, hit.text || ""));
  card.appendChild(quote);

  if (hit.text_source === "asr") {
    card.appendChild(el("p", "asr", "Wording follows the recording."));
  }

  var audioHref = safeUrl(hit.audio_url);
  var youtube = youtubeWatchUrl(hit.audio_url);
  var spoken = readerLabel(hit, audioHref);

  if (hit.start_s == null) {
    card.appendChild(el("p", "timing", "Audio timing coming soon"));
  } else {
    var startLabel = formatTime(hit.start_s);
    var endLabel = formatTime(hit.end_s);
    var range = endLabel ? startLabel + "–" + endLabel : startLabel;
    card.appendChild(el("p", "timing", range));
    if (youtube && startLabel) {
      /* Stored watch URL, including its &t= pre-roll. Not loaded in <audio>. */
      var watch = el("a", "play", "Watch on YouTube at " + startLabel);
      watch.href = youtube;
      watch.target = "_blank";
      watch.rel = "noopener noreferrer";
      card.appendChild(watch);
    } else if (audioHref && startLabel) {
      var button = el("button", "play", "Play from " + startLabel);
      button.type = "button";
      var sermonName = hit.sermon_number != null ? "sermon " + hit.sermon_number : (hit.sermon_title || "this sermon");
      button.setAttribute("aria-label", "Play " + sermonName + " from " + startLabel);
      var caption = (hit.sermon_title || "Sermon");
      if (startLabel) caption += " · " + startLabel;
      if (spoken) caption += " · " + spoken;
      button.addEventListener("click", function () {
        playClip(audioHref, hit.start_s, button, caption);
      });
      card.appendChild(button);
    } else {
      card.appendChild(el("p", "timing", "No recording is linked for this passage yet."));
    }
  }

  if (spoken) card.appendChild(el("p", "reader", spoken));

  var described = sourceLinkFor(hit.source_url, youtube);
  if (described) {
    var link = el("a", null, described.text);
    link.href = described.href;
    link.rel = "noreferrer";
    var line = el("p", "text-link");
    line.appendChild(link);
    card.appendChild(line);
  }

  return item;
}

/* Page copy for each search state. Plain words; inserted with textContent. */
var MESSAGES = {
  loading: "Searching the sermons.",
  nothing: "Nothing found in these sermons.",
  emptyHint: "Try other words, or a Bible verse such as Romans 8:16.",
  low: "Low confidence: these passages may not answer your question. " +
    "This is a rough automatic check (a heuristic), so read them and judge for yourself.",
  lowHidden: "Low-confidence results hidden.",
  weak: "These passages may not answer your question. They are the closest matches, not strong ones.",
  network: "Could not reach the search. Check your connection and try again.",
  server: "The search had a problem on our side. Try again in a moment.",
  garbled: "The search sent back something unexpected. Try again.",
  enter: "Enter a question.",
};

/* "Hide low-confidence results" toggle. Off by default: the low-confidence
   check is a heuristic fitted on very few questions and wrongly flags some
   good answers, so results are shown under a banner unless the person asks
   to hide them. The choice holds for later searches on this page. */
var hideLowConfidence = false;

function countLabel(count) {
  return count === 1 ? "1 passage." : count + " passages.";
}

/* What the page shows for one search response. Pure (no DOM), so it is
   tested in Deno. kind: results | weak | low | empty. ``hideLow`` is the
   toggle; it only affects low-confidence (abstain) responses. */
function describeResponse(data, hideLow) {
  var results = data && Array.isArray(data.results) ? data.results : [];
  var confidence = data && data.confidence && typeof data.confidence === "object" ? data.confidence : {};
  var serverNote = typeof confidence.note === "string" && confidence.note ? confidence.note : null;
  var fallback = data && typeof data.note === "string" && data.note ? data.note : null;
  var state = {
    kind: "results",
    status: countLabel(results.length),
    confidenceNote: null,
    fallbackNote: fallback,
    showResults: true,
    canHide: false,
    results: results,
  };
  if (results.length === 0) {
    state.kind = "empty";
    state.status = MESSAGES.nothing + " " + MESSAGES.emptyHint;
    state.showResults = false;
  } else if (data.abstain === true) {
    state.kind = "low";
    state.canHide = true;
    state.confidenceNote = MESSAGES.low;
    if (hideLow === true) {
      state.status = MESSAGES.lowHidden;
      state.showResults = false;
    }
  } else if (confidence.level === "weak") {
    state.kind = "weak";
    state.confidenceNote = serverNote || MESSAGES.weak;
  }
  return state;
}

/* Status text for a failed search. kind: network | http | garbled. */
function failureMessage(kind, status, data) {
  if (kind === "network") return MESSAGES.network;
  if (kind === "garbled") return MESSAGES.garbled;
  if (typeof status === "number" && status >= 500) return MESSAGES.server;
  if (data && typeof data.error === "string" && data.error) return "Search failed: " + data.error + ".";
  return MESSAGES.server;
}

var lastSearch = null;
var lastData = null;

function setText(id, text) {
  var node = document.getElementById(id);
  node.textContent = text || "";
  node.hidden = !text;
}

function setBusy(busy) {
  var section = document.getElementById("results-section");
  section.setAttribute("aria-busy", busy ? "true" : "false");
  section.classList.toggle("is-loading", busy);
}

function resetState() {
  document.getElementById("results").replaceChildren();
  setText("note", "");
  setText("confidence", "");
  document.getElementById("hide-low").hidden = true;
  document.getElementById("retry").hidden = true;
  document.getElementById("status").classList.remove("is-error");
}

function renderList(results) {
  var list = document.getElementById("results");
  list.replaceChildren();
  for (var i = 0; i < results.length; i += 1) {
    list.appendChild(renderCard(results[i]));
  }
}

function showResults(data) {
  resetState();
  setBusy(false);
  lastData = data;
  var state = describeResponse(data, hideLowConfidence);
  setText("note", state.fallbackNote);
  document.getElementById("status").textContent = state.status;
  if (state.showResults) {
    setText("confidence", state.confidenceNote);
    renderList(state.results);
  }
  var toggle = document.getElementById("hide-low");
  toggle.hidden = !state.canHide;
  toggle.setAttribute("aria-pressed", hideLowConfidence ? "true" : "false");
}

function toggleLowConfidence() {
  hideLowConfidence = !hideLowConfidence;
  if (!lastData) return;
  showResults(lastData);
  /* Keep focus on the toggle so it can be pressed again. */
  document.getElementById("hide-low").focus();
}

function showFailure(message) {
  resetState();
  setBusy(false);
  lastData = null;
  var statusEl = document.getElementById("status");
  statusEl.textContent = message;
  statusEl.classList.add("is-error");
  document.getElementById("retry").hidden = !lastSearch;
}

async function runSearch(query) {
  var statusEl = document.getElementById("status");
  var modeEl = document.getElementById("mode");
  var mode = modeEl.value;
  if (mode !== "hybrid" && mode !== "bm25" && mode !== "dense") mode = "hybrid";
  if (searchAbort) searchAbort.abort();
  searchAbort = new AbortController();
  var signal = searchAbort.signal;
  lastSearch = query;
  lastData = null;
  resetState();
  setBusy(true);
  statusEl.textContent = MESSAGES.loading;

  var params = new URLSearchParams();
  params.set("q", query);
  params.set("k", "10");
  params.set("mode", mode);
  params.set("library", "wesley");

  var response;
  var text;
  try {
    response = await fetch("/api/search?" + params.toString(), {
      headers: { Accept: "application/json" },
      signal: signal,
    });
    text = await response.text();
  } catch (err) {
    if (err && err.name === "AbortError") return;
    showFailure(failureMessage("network"));
    return;
  }
  if (signal.aborted) return;

  var data = null;
  try {
    data = JSON.parse(text);
  } catch (err) {
    showFailure(failureMessage(response.ok ? "garbled" : "http", response.status, null));
    return;
  }
  if (!response.ok) {
    showFailure(failureMessage("http", response.status, data));
    return;
  }
  showResults(data);
}

function init() {
  var audio = document.getElementById("player");
  ["loadedmetadata", "canplay", "durationchange"].forEach(function (name) {
    audio.addEventListener(name, function () { seekWhenReady(audio); });
  });

  var form = document.getElementById("search-form");
  var input = document.getElementById("q");

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var query = input.value.trim();
    if (!query) {
      document.getElementById("status").textContent = MESSAGES.enter;
      input.focus();
      return;
    }
    runSearch(query);
  });

  document.getElementById("hide-low").addEventListener("click", toggleLowConfidence);
  document.getElementById("retry").addEventListener("click", function () {
    if (lastSearch) runSearch(lastSearch);
  });

  document.querySelectorAll("[data-query]").forEach(function (button) {
    button.addEventListener("click", function () {
      input.value = button.getAttribute("data-query") || "";
      form.requestSubmit();
    });
  });

  var initial = new URLSearchParams(window.location.search).get("q");
  if (initial && initial.trim()) {
    input.value = initial.trim();
    runSearch(input.value);
  }
}

document.addEventListener("DOMContentLoaded", init);
