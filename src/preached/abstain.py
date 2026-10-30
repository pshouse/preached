"""Honest "nothing found": how much evidence a result list has.

No model is asked anything. The rule reads two signals the ranker already has:

1. **Agreement** (binary, no parameter). Some result on the page is ranked
   by both BM25 and dense search, each within its top ``CANDIDATES`` (100,
   the depth reciprocal rank fusion already uses). If no shown passage is
   found by both, the words of the question and its meaning point to
   different places, or the words do not occur at all.
2. **Dense floor** (one number per model). The top dense cosine against
   ``floor``. Cosines are not comparable across models (Granite's
   unanswerable questions top out near 0.83, EmbeddingGemma 2's near 0.75),
   so ``floor`` is calibrated per model and stored in ``search/abstain.toml``
   with the fingerprints of the vectors it was fitted on.

Levels:

- ``strong``: agreement, and the top cosine is above the floor.
- ``weak``: exactly one of the two fails. Results are shown with a note that
  they may not answer the question.
- ``none``: both fail. The page says nothing strong was found. The closest
  passages are still returned (``abstain`` is true) so a person can look.
- ``unrated``: BM25-only search with results; there is no dense signal.

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
import math
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from preached.paths import repo_root
from preached.rank import dense_hits, dense_scores
from preached.store import bm25_search

CANDIDATES = 100
# Stored floors are rounded up to this many decimals, so a fitted question
# that sat exactly on the floor still compares <= after rounding.
FLOOR_DECIMALS = 4

NONE_NOTE = "Nothing strong found in these sermons."
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
    """
    lexical = bm25_search(searcher.connection, query, CANDIDATES)
    if vector is None or searcher._matrix is None:
        return Signals(bm25_hits=len(lexical), dense_top=None, agreement=False)
    scores = dense_scores(vector, searcher._matrix)
    semantic = dense_hits(searcher._rowids, scores, CANDIDATES)
    both = {rowid for rowid, _ in lexical} & {rowid for rowid, _ in semantic}
    dense_top = float(semantic[0][1]) if semantic else None
    return Signals(
        bm25_hits=len(lexical),
        dense_top=dense_top,
        agreement=any(hit.rowid in both for hit in shown),
    )


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


def load_calibrations(path: Path | None = None) -> dict:
    path = path or calibration_path()
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text()).get("models", {})


def floor_for(model: str | None, path: Path | None = None) -> float | None:
    """The calibrated floor for ``model``, or None when it has none or the
    stored fingerprints no longer match search/models.toml."""
    if not model:
        return None
    from preached.models import MODELS

    spec = MODELS.get(model)
    entry = load_calibrations(path).get(model)
    if spec is None or not entry:
        return None
    if entry.get("fingerprint") != spec.fingerprint():
        return None
    if entry.get("query_fingerprint") != query_fingerprint(spec):
        return None
    floor = entry.get("dense_floor")
    if not isinstance(floor, (int, float)) or isinstance(floor, bool):
        return None
    return float(floor)


def calibration_toml(entries: dict[str, dict]) -> str:
    """search/abstain.toml text. ``entries``: model key -> fields."""
    lines = [
        "# Per-model dense floor for the abstain rule (src/preached/abstain.py).",
        "# Written by: uv run --group bench search/bench.py --abstain --write-calibration",
        "# A floor applies only while both fingerprints match search/models.toml;",
        "# otherwise that model never abstains (results with a note at most).",
        "# Fitted on LLM-written eval labels pending human review (eval/README.md).",
        "",
    ]
    for key in sorted(entries):
        entry = entries[key]
        lines.append(f"[models.{key}]")
        for field in ("dense_floor", "fingerprint", "query_fingerprint", "fitted_on", "results"):
            if field not in entry or entry[field] is None:
                continue
            value = entry[field]
            lines.append(f"{field} = {json.dumps(value)}")
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
