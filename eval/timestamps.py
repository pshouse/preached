"""Do the top hits land on the right moment of the audio, not just the right text?

For every answerable eval question, run the app's default search (hybrid, RRF,
the same call as search/query.py) and compare each hit's [start_s, end_s] with
the gold quote's aligned time span. The gold span comes from W1-C's per-word
times in /cache/aligned/wesley/<sermon>.json, located by matching the quote's
words in the sermon's word stream. Then it picks random top-1 hits and compares
the chunk text with the W1-A Whisper words in that time window.

  uv run eval/timestamps.py [--seed 20261030] [--out reports/W1-CLI-timestamps.json]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "align"))

from preached import env  # noqa: F401, E402
from preached.corpus import read_jsonl, word_tokens  # noqa: E402
from preached.embed import encode_query, load_model, unload  # noqa: E402
from preached.metrics import contains_quote  # noqa: E402
from preached.models import DEFAULT_MODEL, MODELS  # noqa: E402
from preached.paths import CACHE_ROOT, INDEX_CHUNKS_JSONL, INDEX_PATH, SERMONS_JSONL  # noqa: E402
from preached.search import Searcher  # noqa: E402
from preached.store import connect  # noqa: E402
from textnorm import asr_tokens, canonical_tokens  # noqa: E402

ALIGNED = CACHE_ROOT / "aligned" / "wesley"
TRANSCRIPTS = CACHE_ROOT / "transcripts" / "wesley"
TOP_K = 5


def quote_spans(quote: str, tokens: list[str]) -> list[tuple[int, int]]:
    """Every [start, end) token range in `tokens` equal to the quote's words."""
    want = [w.lower() for w in word_tokens(quote)]
    have = [w.lower() for w in tokens]
    return [(i, i + len(want)) for i in range(len(have) - len(want) + 1) if have[i : i + len(want)] == want]


def gold_spans(question: dict, sermons: dict, aligned_cache: dict) -> list[dict]:
    """One entry per (passage, occurrence). Like the text metric, which counts a
    chunk from any sermon that contains the quote, every occurrence counts: a
    sermon often repeats its text verse, and some verses open two sermons."""
    spans = []
    for passage in question["relevant"]:
        found_any = False
        for sid, sermon in sermons.items():
            tokens = word_tokens(sermon["text"])
            for found in quote_spans(passage["quote"], tokens):
                if sid not in aligned_cache:
                    aligned_cache[sid] = json.load(open(ALIGNED / f"{sid}.json"))
                aligned = aligned_cache[sid]
                first, last = aligned["words"][found[0]], aligned["words"][found[1] - 1]
                found_any = True
                spans.append({
                    "passage": passage,
                    "sermon_id": sid,
                    "words": found,
                    "file_id": aligned["audio"][first[0]]["file_id"],
                    "start_s": first[1],
                    "end_s": last[2],
                })
        if not found_any:
            spans.append({"passage": passage, "error": "quote not found in any sermon"})
    return spans


def judge(hit, chunk_file_id: str | None, span: dict) -> dict:
    """Relations between a hit's play position and one gold span."""
    if "error" in span:
        return {"inside": False, "overlap": False}
    same_file = chunk_file_id in (None, span["file_id"])
    start, end = hit.start_s, hit.end_s
    inside = same_file and span["start_s"] <= start <= span["end_s"]
    overlap = same_file and start < span["end_s"] and end > span["start_s"]
    # Playing from start_s reaches the first gold word within the chunk length.
    return {"inside": inside, "overlap": overlap, "lead_s": span["start_s"] - start if same_file else None}


def window_overlap(chunk: dict) -> dict:
    """Chunk text against the Whisper words heard in the chunk's time window."""
    transcript = json.load(open(TRANSCRIPTS / f"{chunk['audio_file_id']}.json"))
    heard = [
        w for seg in transcript["segments"] for s, e, w in seg["words"]
        if s >= chunk["start_s"] - 0.3 and e <= chunk["end_s"] + 0.3
    ]
    heard_tokens = [t for t, _ in asr_tokens(heard)]
    text_tokens = [t for t, _ in canonical_tokens(chunk["text"])]
    common = sum((Counter(text_tokens) & Counter(heard_tokens)).values())
    return {
        "chunk_words": len(text_tokens),
        "whisper_words": len(heard_tokens),
        "chunk_covered": round(common / max(len(text_tokens), 1), 3),
        "whisper_covered": round(common / max(len(heard_tokens), 1), 3),
        "whisper_sample": " ".join(heard[:18]) + " ...",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20261030)
    parser.add_argument("--out", type=Path, default=ROOT / "reports" / "W1-CLI-timestamps.json")
    args = parser.parse_args()

    questions = [json.loads(line) for line in open(ROOT / "eval" / "questions.jsonl")]
    sermons = {row["sermon_id"]: row for row in read_jsonl(SERMONS_JSONL)}
    chunk_rows = {row["chunk_id"]: row for row in read_jsonl(INDEX_CHUNKS_JSONL)}
    connection = connect(INDEX_PATH)
    spec = MODELS[DEFAULT_MODEL]
    loaded = load_model(spec, device="cpu", batch_size=1)
    searcher = Searcher(connection, model=DEFAULT_MODEL)
    cache: dict = {}
    rows = []
    try:
        for q in questions:
            vector = encode_query(loaded, q["query"])
            hits = searcher.hybrid(q["query"], vector, TOP_K)
            row = {"id": q["id"], "type": q["type"], "query": q["query"]}
            row["top1"] = {"chunk_id": hits[0].chunk_id, "start_s": hits[0].start_s} if hits else None
            if q["relevant"]:
                spans = gold_spans(q, sermons, cache)
                row["gold"] = [
                    {k: v for k, v in s.items() if k != "passage"} | {"grade": s["passage"]["grade"]} for s in spans
                ]
                for label, grades in (("g2", {2}), ("any", {1, 2})):
                    use = [s for s in spans if s["passage"]["grade"] in grades]
                    per_rank = []
                    for hit in hits:
                        fid = chunk_rows[hit.chunk_id].get("audio_file_id")
                        per_rank.append([judge(hit, fid, s) for s in use])
                    for key in ("inside", "overlap"):
                        ranks = [i + 1 for i, js in enumerate(per_rank) if any(j[key] for j in js)]
                        row[f"{label}_{key}_first_rank"] = ranks[0] if ranks else None
                text_ranks = [i + 1 for i, h in enumerate(hits)
                              if any(contains_quote(h.text, p["quote"]) for p in q["relevant"] if p["grade"] == 2)]
                row["g2_text_first_rank"] = text_ranks[0] if text_ranks else None
                if hits:
                    row["top1_lead_s"] = min((x for x in (judge(hits[0], chunk_rows[hits[0].chunk_id].get("audio_file_id"), sp).get("lead_s") for sp in spans if sp["passage"]["grade"] == 2) if x is not None), key=abs, default=None)
            rows.append(row)
    finally:
        unload(loaded)

    answerable = [r for r in rows if r["type"] != "unanswerable"]
    summary = {"questions": len(rows), "answerable": len(answerable)}
    for label in ("g2", "any"):
        for key in ("inside", "overlap", "text"):
            if key == "text" and label == "any":
                continue
            ranks = [r[f"{label}_{key}_first_rank"] for r in answerable]
            summary[f"{label}_{key}_hit@1"] = sum(1 for x in ranks if x == 1)
            summary[f"{label}_{key}_hit@5"] = sum(1 for x in ranks if x is not None)

    # Spot check: 5 random answerable questions' top-1 chunks vs Whisper words.
    rng = random.Random(args.seed)
    picks = rng.sample(answerable, 5)
    spot = []
    for r in picks:
        chunk = chunk_rows[r["top1"]["chunk_id"]]
        spot.append({"id": r["id"], "chunk_id": chunk["chunk_id"], "start_s": chunk["start_s"], "end_s": chunk["end_s"],
                     "audio_file_id": chunk["audio_file_id"], **window_overlap(chunk)})
    args.out.write_text(json.dumps({"summary": summary, "questions": rows, "spot_check": spot}, indent=1))
    print(json.dumps(summary, indent=1))
    for s in spot:
        print(s)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
