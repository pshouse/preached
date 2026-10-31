"""Honest "nothing found": how much evidence a result list has.

No model is asked anything. The rule reads two signals the ranker already has:

1. **Agreement** (binary, no parameter). Some result on the page is ranked
   by both BM25 and dense search, each within its top ``CANDIDATES`` (100,
   the depth reciprocal rank fusion already uses). If no shown passage is
   found by both, the words of the question and its meaning point to
   different places, or the words do not occur at all.
2. **Dense floor** (one number per model, backend, and variant). The top
   dense cosine against ``floor``. Cosines are not comparable across models
   (Granite's unanswerable questions top out near 0.83, EmbeddingGemma 2's
   near 0.75), or across backends (int8 ONNX moves the top cosine), so
   ``floor`` is calibrated per (model, backend, variant) and stored in
   ``search/abstain.toml`` with the fingerprints of the vectors it was
   fitted on.

Levels:

- ``strong``: agreement, and the top cosine is above the floor.
- ``weak``: exactly one of the two fails. Results are shown with a note that
  they may not answer the question.
- ``none``: both fail ("low confidence"; ``abstain`` is true). The passages
  are still returned and the page shows them by default under a
  low-confidence banner, with a toggle to hide them.
- ``unrated``: BM25-only search with results; there is no dense signal.

The dense floor is a heuristic, not a verdict: it is fitted on five
LLM-written unanswerable questions and in practice is set by one of them
(``u-book-of-mormon``). It wrongly flags some answerable questions (e.g.
"worry", "How do I stop worrying?", which Sermon 29 covers) and passes a
bare ``"``. That is why the page and CLI show low-confidence results by
default. See reports/W3-POLISH.md.

A model with no calibration (or a stale one) never abstains; a list without
agreement is ``weak``. BM25-only search abstains only when it found nothing.

``fit_floor`` picks the floor from labelled questions: the highest top cosine
among unanswerable questions that have no agreement, so "nothing found" is
said only when the evidence is no better than for a question known to have
no answer. If that would put a labelled answerable question without
agreement into ``none``, the floor drops just below it. Biased toward showing
results: a false "nothing found" hides a real answer.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from preached.paths import repo_root
from preached.store import bm25_search

log = logging.getLogger(__name__)

CANDIDATES = 100
# The query embedder the shipped floors were fitted with. A floor applies
# only to the backend and variant it was fitted on: int8 ONNX lowers the top
# cosine by 0.008-0.053 (PR #10) and the document fingerprint cannot see it.
# For torch the variant is the CPU dtype.
DEFAULT_BACKEND = "torch"
# Stored floors are rounded up to this many decimals, so a fitted question
# that sat exactly on the floor still compares <= after rounding.
FLOOR_DECIMALS = 4

NONE_NOTE = (
    "Low confidence: these passages may not answer your question. "
    "This is a rough automatic check (a heuristic), so read them and judge for yourself."
)
WEAK_NOTE = "These passages may not answer your question. They are the closest matches, not strong ones."


@dataclass(frozen=True)
class Signals:
    bm25_hits: int
    dense_top: float | None
    agreement: bool


@dataclass(frozen=True)
class Confidence:
    level: str  # strong | weak | none | unrated
    calibrated: bool
    floor: float | None
    signals: Signals

    @property
    def abstain(self) -> bool:
        return self.level == "none"

    @property
    def note(self) -> str | None:
        if self.level == "none":
            return NONE_NOTE
        if self.level == "weak":
            return WEAK_NOTE
        return None

    def as_dict(self) -> dict:
        return {
            "level": self.level,
            "calibrated": self.calibrated,
            "note": self.note,
            "signals": asdict(self.signals),
        }


def compute_signals(searcher, query: str, vector, shown) -> Signals:
    """Signals for ``shown`` (the hits the page will list).

    BM25 and dense are run again at ``CANDIDATES``. That is a few
    milliseconds and leaves the ranking code untouched. With no vector
    (BM25-only search) ``dense_top`` is None and agreement is False.

    Both run through the publish gate (``searcher._where()``), the same as
    the results: a chunk the reader may not see never adds a BM25 hit,
    raises ``dense_top`` or makes agreement. Otherwise ``bm25_hits`` would
    tell anyone whether a word occurs in an unpublished sermon.
    """
    where = searcher._where()
    lexical = bm25_search(searcher.connection, query, CANDIDATES, where)
    if vector is None or searcher._matrix is None:
        return Signals(bm25_hits=len(lexical), dense_top=None, agreement=False)
    semantic = searcher._semantic(vector, CANDIDATES, where)
    both = {rowid for rowid, _ in lexical} & {rowid for rowid, _ in semantic}
    dense_top = float(semantic[0][1]) if semantic else None
    return Signals(
        bm25_hits=len(lexical),
        dense_top=dense_top,
        agreement=any(hit.rowid in both for hit in shown),
    )


def church_confidence(signals: Signals, *, has_results: bool) -> Confidence:
    """Confidence for a church library. Unrated until that library is calibrated.

    The floor in ``search/abstain.toml`` was fitted on Wesley. Applying it
    to a church transcript would call the same cosine strong, weak, or low
    on the wrong scale. A list with passages is ``unrated`` (show them, no
    strong/weak/low claim). An empty list is ``none`` only as "nothing
    found", with ``calibrated`` false and no floor.
    """
    if not has_results:
        return Confidence(level="none", calibrated=False, floor=None, signals=signals)
    return Confidence(level="unrated", calibrated=False, floor=None, signals=signals)


def decide(signals: Signals, floor: float | None, has_results: bool = True) -> Confidence:
    """The level for one search. ``floor`` None means uncalibrated."""
    calibrated = floor is not None
    if not has_results:
        level = "none"
    elif signals.dense_top is None:
        level = "unrated"
    else:
        low = calibrated and signals.dense_top <= floor
        if not signals.agreement and low:
            level = "none"
        elif not signals.agreement or low:
            level = "weak"
        else:
            level = "strong"
    return Confidence(level=level, calibrated=calibrated, floor=floor, signals=signals)


def round_up(value: float, decimals: int = FLOOR_DECIMALS) -> float:
    scale = 10 ** decimals
    return math.ceil(value * scale - 1e-9) / scale


def fit_floor(rows: list[tuple[Signals, bool]]) -> float | None:
    """Fit the dense floor from (signals, answerable) pairs.

    Returns None when no unanswerable question lacks agreement (nothing to
    calibrate against; the model then never abstains).
    """
    negatives = [s.dense_top for s, answerable in rows
                 if not answerable and not s.agreement and s.dense_top is not None]
    if not negatives:
        return None
    floor = round_up(max(negatives))
    guarded = [s.dense_top for s, answerable in rows
               if answerable and not s.agreement and s.dense_top is not None]
    below = [value for value in guarded if value <= floor]
    if below:
        # Never fit a floor that hides a labelled answer: sit just under it.
        step = 10 ** -FLOOR_DECIMALS
        floor = math.floor(min(below) / step) * step - step
        floor = round(floor, FLOOR_DECIMALS)
    return floor


# ---------- calibration file ----------

def calibration_path() -> Path:
    return repo_root() / "search" / "abstain.toml"


def query_fingerprint(spec) -> str:
    """What changes a query vector (and so its cosines) but not the stored
    document vectors: query prefixes and the CPU dtype."""
    parts = {
        "question_prefix": spec.question_prefix,
        "keyword_prefix": spec.keyword_prefix,
        "dtype_cpu": spec.dtype_cpu,
    }
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def load_calibrations(path: Path | None = None) -> list[dict]:
    """The ``[[models]]`` entries of the calibration file.

    One entry per (model, backend, variant). A missing file is no
    calibration. An unreadable or malformed file (not UTF-8, bad TOML,
    ``models`` not an array of tables) is logged and also treated as no
    calibration, so a bad edit can never stop the server: search keeps
    working and simply never abstains on dense evidence.
    """
    path = path or calibration_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("ignoring %s: cannot read it (%s); abstain floor disabled", path, exc)
        return []
    try:
        models = tomllib.loads(text).get("models", [])
    except tomllib.TOMLDecodeError as exc:
        log.warning("ignoring %s: not valid TOML (%s); abstain floor disabled", path, exc)
        return []
    if not isinstance(models, list) or any(not isinstance(entry, dict) for entry in models):
        log.warning("ignoring %s: 'models' is not an array of tables; abstain floor disabled", path)
        return []
    return models


def embedder_variant(spec, backend: str, variant: str | None) -> str | None:
    """The variant a floor is keyed on: as given, or the CPU dtype for torch."""
    if variant is None and backend == "torch":
        return spec.dtype_cpu
    return variant


def floor_for(
    model: str | None,
    path: Path | None = None,
    *,
    backend: str = DEFAULT_BACKEND,
    variant: str | None = None,
) -> float | None:
    """The calibrated floor for ``model`` on this query embedder, or None.

    None when that (model, backend, variant) has no entry, more than one
    entry, the stored fingerprints no longer match search/models.toml, or
    ``dense_floor`` is not a finite number in [-1, 1] (a cosine; 1 and -1
    count). Never raises on a bad file.
    """
    if not model:
        return None
    from preached.models import MODELS

    spec = MODELS.get(model)
    if spec is None:
        return None
    where = path or calibration_path()
    wanted = embedder_variant(spec, backend, variant)
    matches = [
        entry for entry in load_calibrations(path)
        if entry.get("model") == model and entry.get("backend") == backend and entry.get("variant") == wanted
    ]
    if not matches:
        return None
    if len(matches) > 1:
        log.warning(
            "ignoring %s: more than one floor for %s %s %s; abstain floor disabled",
            where, model, backend, wanted,
        )
        return None
    entry = matches[0]
    if entry.get("fingerprint") != spec.fingerprint():
        return None
    if entry.get("query_fingerprint") != query_fingerprint(spec):
        return None
    floor = entry.get("dense_floor")
    # 1 and -1 are cosines (the fixture vectors sit at 1). +inf, nan, and
    # anything outside [-1, 1] are not.
    if not isinstance(floor, (int, float)) or isinstance(floor, bool) or not math.isfinite(floor) \
            or not -1.0 <= floor <= 1.0:
        log.warning(
            "ignoring %s: dense_floor %r for %s %s %s is not a cosine in [-1, 1]; abstain floor disabled",
            where, floor, model, backend, wanted,
        )
        return None
    return float(floor)


def _toml_value(field: str, value) -> str:
    if field == "dense_floor" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{float(value):.4f}"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value)


def calibration_toml(entries: list[dict]) -> str:
    """search/abstain.toml text. ``entries``: one dict per (model, backend, variant)."""
    lines = [
        "# Dense floors for the abstain rule (src/preached/abstain.py).",
        "# One [[models]] entry per (model, backend, variant).",
        "# Written by: uv run --group bench search/bench.py --abstain --write-calibration",
        "# A floor applies only while both fingerprints match search/models.toml and",
        "# the query embedder is that backend and variant; otherwise that combination",
        "# never abstains (results with a note at most). The floor is a",
        "# heuristic: it rests on very few unanswerable questions (reports/W3-POLISH.md).",
        "# Fitted on LLM-written eval labels pending human review (eval/README.md).",
        "",
    ]
    fields = ("model", "backend", "variant", "dense_floor", "fingerprint", "query_fingerprint", "fitted_on", "results")
    ordered = sorted(entries, key=lambda entry: (
        str(entry.get("model")), str(entry.get("backend")), str(entry.get("variant")),
    ))
    for entry in ordered:
        lines.append("[[models]]")
        for field in fields:
            if field not in entry or entry[field] is None:
                continue
            lines.append(f"{field} = {_toml_value(field, entry[field])}")
        lines.append("")
    return "\n".join(lines)


def search_with_confidence(searcher, query: str, vector, mode: str, k: int, floor: float | None):
    """``api_search`` plus the confidence of the list. GET /api/search,
    search/query.py and search/bench.py --abstain all call this.

    Returns (hits, Confidence). On ``none`` the hits are still returned so a
    person can look; the caller decides whether to show them.
    """
    from preached.search import api_search

    hits = api_search(searcher, query, vector, mode, k)
    signals = compute_signals(searcher, query, None if mode == "bm25" else vector, hits)
    return hits, decide(signals, floor if mode != "bm25" else None, has_results=bool(hits))
