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

function safeUrl(value) {
  if (typeof value !== "string" || value === "") return null;
  try {
    var url = new URL(value, window.location.origin);
  } catch (err) {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
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
  var seconds = Number(start);
  audio.dataset.token = String(token);
  audio.dataset.seek = Number.isFinite(seconds) ? String(seconds) : "";
  if (audio.dataset.srcUrl !== url) {
    audio.dataset.srcUrl = url;
    audio.src = Number.isFinite(seconds) ? url + "#t=" + seconds : url;
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

  var source = safeUrl(hit.source_url);
  var audioHref = safeUrl(hit.audio_url);
  var spoken = readerLabel(hit, audioHref);

  if (hit.start_s == null) {
    card.appendChild(el("p", "timing", "Audio timing coming soon"));
  } else {
    var startLabel = formatTime(hit.start_s);
    var endLabel = formatTime(hit.end_s);
    var range = endLabel ? startLabel + "–" + endLabel : startLabel;
    card.appendChild(el("p", "timing", range));
    if (audioHref && startLabel) {
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

  if (source) {
    var link = el("a", null, "Read this sermon on CCEL");
    link.href = source;
    link.rel = "noreferrer";
    var line = el("p", "text-link");
    line.appendChild(link);
    card.appendChild(line);
  }

  return item;
}

function showResults(data) {
  var noteEl = document.getElementById("note");
  var statusEl = document.getElementById("status");
  var list = document.getElementById("results");
  list.replaceChildren();

  if (data.note) {
    noteEl.hidden = false;
    noteEl.textContent = data.note;
  } else {
    noteEl.hidden = true;
    noteEl.textContent = "";
  }

  var results = Array.isArray(data.results) ? data.results : [];
  if (results.length === 0) {
    statusEl.textContent = "Nothing strong found";
    return;
  }
  statusEl.textContent = results.length === 1 ? "1 passage." : results.length + " passages.";
  for (var i = 0; i < results.length; i += 1) {
    list.appendChild(renderCard(results[i]));
  }
}

function showFailure(message) {
  document.getElementById("note").hidden = true;
  document.getElementById("results").replaceChildren();
  document.getElementById("status").textContent = message;
}

async function runSearch(query) {
  var statusEl = document.getElementById("status");
  var modeEl = document.getElementById("mode");
  var mode = modeEl.value;
  if (mode !== "hybrid" && mode !== "bm25" && mode !== "dense") mode = "hybrid";
  if (searchAbort) searchAbort.abort();
  searchAbort = new AbortController();
  var signal = searchAbort.signal;
  statusEl.textContent = "Searching.";
  document.getElementById("results").replaceChildren();
  document.getElementById("note").hidden = true;

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
    showFailure("Search failed. Try again.");
    return;
  }
  if (signal.aborted) return;

  var data = null;
  try {
    data = JSON.parse(text);
  } catch (err) {
    showFailure("Search failed. Try again.");
    return;
  }
  if (!response.ok) {
    var problem = data && typeof data.error === "string" ? data.error : "Search failed. Try again.";
    showFailure(problem);
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
      document.getElementById("status").textContent = "Enter a question.";
      input.focus();
      return;
    }
    runSearch(query);
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
