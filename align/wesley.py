"""Align Wesley's canonical CCEL text to the LibriVox audio (W1-C).

Whisper output is used only for timing. The searchable text is Wesley's
published words from ``/cache/corpus/wesley/sermons.jsonl`` (W1-B).

    python3 align/wesley.py map      # manifest + canonical mapping, verified by text overlap
    python3 align/wesley.py align    # per-sermon JSON in /cache/aligned/wesley/
    python3 align/wesley.py chunks   # /cache/corpus/wesley/chunks_aligned.jsonl
    python3 align/wesley.py qa       # coverage per file + 10 spot-checked sentences
    python3 align/wesley.py all      # the four steps in order

Stdlib only. Reads W1-A transcripts from /cache/transcripts/wesley/.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from preached.corpus import (  # noqa: E402
    chunk_sermon,
    load_chunk_config,
    read_jsonl,
    split_sentences,
    word_tokens,
    write_jsonl,
)
from seqalign import EXACT, FUZZY, align_tokens, interpolate  # noqa: E402
from textnorm import asr_tokens, canonical_tokens  # noqa: E402

CACHE = Path(os.environ.get("PREACHED_CACHE", "/cache"))
TRANSCRIPTS = CACHE / "transcripts" / "wesley"
SERMONS_JSONL = CACHE / "corpus" / "wesley" / "sermons.jsonl"
ALIGNED_DIR = CACHE / "aligned" / "wesley"
CHUNKS_ALIGNED = CACHE / "corpus" / "wesley" / "chunks_aligned.jsonl"
SOURCE_MANIFEST = ROOT.parent / "w1-ingest" / "ingest" / "manifest" / "wesley.jsonl"
MANIFEST = ROOT / "align" / "manifest" / "wesley.jsonl"
QA_JSON = ALIGNED_DIR / "qa.json"
CCEL_TEXT_URL = "https://www.ccel.org/ccel/w/wesley/sermons/cache/sermons.txt"
COVERAGE_FLAG = 0.90


# --------------------------------------------------------------------------
# inputs


def load_sermons() -> dict[str, dict]:
    return {row["sermon_id"]: row for row in read_jsonl(SERMONS_JSONL)}


def load_manifest(path: Path = MANIFEST) -> list[dict]:
    return read_jsonl(path)


def searchable_words(transcript: dict) -> list[tuple[float, float, str]]:
    """Whisper words inside the sermon window (LibriVox intro/outro excluded)."""
    lo, hi = transcript["searchable_start"], transcript["searchable_end"]
    words = []
    for segment in transcript["segments"]:
        if segment.get("boilerplate"):
            continue
        for start, end, word in segment["words"]:
            if lo <= start < hi:
                words.append((start, end, word))
    words.sort(key=lambda item: item[0])
    return words


def load_transcript(file_id: str) -> dict:
    return json.loads((TRANSCRIPTS / f"{file_id}.json").read_text())


# --------------------------------------------------------------------------
# map: file -> canonical sermon, checked against the words actually read


def _trigrams(tokens: list[str]) -> set[tuple[str, str, str]]:
    return set(zip(tokens, tokens[1:], tokens[2:]))


def cmd_map(args: argparse.Namespace) -> None:
    sermons = load_sermons()
    sermon_grams = {
        sid: _trigrams([tok for tok, _ in canonical_tokens(row["text"])]) for sid, row in sermons.items()
    }
    rows = read_jsonl(Path(args.source_manifest))
    parts = Counter(row["wesley_sermon_number"] for row in rows if row["wesley_sermon_number"])
    seen: Counter = Counter()
    problems = 0
    for row in rows:
        number = row["wesley_sermon_number"]
        grams = _trigrams([tok for tok, _ in asr_tokens([w for _, _, w in searchable_words(load_transcript(row["id"]))])])
        scored = sorted(
            ((len(grams & g) / max(1, len(grams)), sid) for sid, g in sermon_grams.items()),
            reverse=True,
        )
        best, runner = scored[0], scored[1]
        if number is None:
            row.update(
                canonical_sermon_id=None, canonical_title=None, canonical_source_url=None,
                canonical_part=None, canonical_parts=None,
                canonical_note="LibriVox preface; not one of the 141 sermons, not indexed (W1-B).",
            )
        else:
            sid = f"wesley-{number:03d}"
            seen[number] += 1
            row.update(
                canonical_sermon_id=sid,
                canonical_title=sermons[sid]["title"],
                canonical_source_url=sermons[sid]["source_url"],
                canonical_part=seen[number],
                canonical_parts=parts[number],
            )
            if best[1] != sid:
                problems += 1
                print(f"MISMATCH {row['id']}: manifest {sid}, text overlap says {best[1]}", file=sys.stderr)
        row["mapping_check"] = {
            "method": "share of the file's Whisper word trigrams found in each CCEL sermon",
            "best": best[1], "best_score": round(best[0], 3),
            "runner_up": runner[1], "runner_up_score": round(runner[0], 3),
        }
        print(f"{row['id']:<18} -> {row.get('canonical_sermon_id')}  overlap {best[0]:.2f} (next {runner[1]} {runner[0]:.2f})")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(MANIFEST, rows)
    print(f"wrote {MANIFEST}: {len(rows)} files, {problems} mapping disagreements")
    if problems:
        raise SystemExit(1)


# --------------------------------------------------------------------------
# align


def sentence_spans(text: str) -> list[dict]:
    """Paragraphs and sentences with canonical token spans (W1-B's splitter)."""
    paragraphs = []
    cursor = 0
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        sentences = []
        for sentence in split_sentences(paragraph):
            count = len(word_tokens(sentence))
            if count:
                sentences.append({"text": sentence, "word_start": cursor, "word_end": cursor + count})
                cursor += count
        if sentences:
            paragraphs.append({"sentences": sentences})
    if cursor != len(word_tokens(text)):
        raise RuntimeError("sentence token spans do not cover the text")
    return paragraphs


def span_times(words: list[list], start: int, end: int) -> tuple[int, float, float, float]:
    """(part, start_s, end_s, anchored share) for canonical tokens [start, end).

    A span that crosses from one audio file to the next (a sermon read in
    two parts) plays from the file holding most of its words.
    """
    part = Counter(w[0] for w in words[start:end]).most_common(1)[0][0]
    same = [w for w in words[start:end] if w[0] == part]
    anchored = sum(1 for w in words[start:end] if w[3]) / max(1, end - start)
    return part, min(w[1] for w in same), max(w[2] for w in same), round(anchored, 3)


def align_sermon(sermon: dict, files: list[dict]) -> dict:
    text = sermon["text"]
    tokens = word_tokens(text)
    canon = canonical_tokens(text)
    ref = [tok for tok, _ in canon]
    hyp: list[str] = []
    hyp_time: list[tuple[int, float, float]] = []
    part_ends: list[float] = []
    audio = []
    for part, row in enumerate(files):
        transcript = load_transcript(row["id"])
        words = searchable_words(transcript)
        for tok, index in asr_tokens([w for _, _, w in words]):
            hyp.append(tok)
            hyp_time.append((part, words[index][0], words[index][1]))
        part_ends.append(words[-1][1] if words else 0.0)
        audio.append({
            "file_id": row["id"], "part": part, "audio_url": row["audio_url"], "reader": row["reader"],
            "duration_s": row["duration_s"], "ia_url": row["ia_url"], "librivox_url": row["librivox_url"],
            "license_url": row["license_url"], "license_note": row["license_note"],
            "searchable_start": transcript["searchable_start"],
            "searchable_end": transcript["searchable_end"],
            "asr_words": len(words),
        })
    anchors = align_tokens(ref, hyp)
    # Canonical token times: union of its anchored normalized pieces.
    times: list[tuple[int, float, float] | None] = [None] * len(tokens)
    kind = [0] * len(tokens)
    for ref_index, (tok, group) in enumerate(canon):
        if ref_index not in anchors:
            continue
        hyp_index, how = anchors[ref_index]
        part, start, end = hyp_time[hyp_index]
        for t in group:
            if times[t] is None:
                times[t] = (part, start, end)
            elif times[t][0] == part:
                times[t] = (part, min(times[t][1], start), max(times[t][2], end))
            kind[t] = EXACT if kind[t] == EXACT or how == EXACT else FUZZY
    # Whisper word times can overlap after normalization joins; keep them monotone.
    last = (-1, 0.0)
    for t, value in enumerate(times):
        if value is None:
            continue
        if (value[0], value[1]) < last:
            times[t], kind[t] = None, 0
            continue
        last = (value[0], value[1])
    filled = interpolate(times, [len(tok) for tok in tokens], part_ends)
    words = [[p, round(s, 3), round(e, 3), kind[i]] for i, (p, s, e) in enumerate(filled)]

    paragraphs = sentence_spans(text)
    for paragraph in paragraphs:
        for sentence in paragraph["sentences"]:
            part, start, end, share = span_times(words, sentence["word_start"], sentence["word_end"])
            sentence.update(part=part, start_s=start, end_s=end, anchored=share)
        first, last_s = paragraph["sentences"][0], paragraph["sentences"][-1]
        part, start, end, share = span_times(words, first["word_start"], last_s["word_end"])
        paragraph.update(part=part, start_s=start, end_s=end, anchored=share,
                         word_start=first["word_start"], word_end=last_s["word_end"])

    exact = sum(1 for k in kind if k == EXACT)
    fuzzy = sum(1 for k in kind if k == FUZZY)
    for item in audio:
        mine = [i for i, w in enumerate(words) if w[0] == item["part"]]
        item["canonical_words"] = len(mine)
        item["coverage"] = round(sum(1 for i in mine if kind[i]) / max(1, len(mine)), 4)
    return {
        "sermon_id": sermon["sermon_id"],
        "sermon_number": sermon["sermon_number"],
        "sermon_title": sermon["title"],
        "scripture": sermon["scripture"],
        "text_source": "canonical",
        "source_url": sermon["source_url"],
        "text_url": CCEL_TEXT_URL,
        "text_note": "Wesley's published text (CCEL, Jackson 1872 numbering, public domain). "
                     "Timestamps come from Whisper word times on the LibriVox reading; the words are not Whisper's.",
        "audio": audio,
        "voice_note": "Read by a volunteer LibriVox reader, NOT Wesley's voice.",
        "alignment": {
            "method": "difflib SequenceMatcher on normalized word tokens; stranded short runs dropped; "
                      "fuzzy pairing in small equal-length gaps; unanchored words interpolated by length",
            "canonical_words": len(tokens),
            "anchored_exact": exact,
            "anchored_fuzzy": fuzzy,
            "coverage": round((exact + fuzzy) / max(1, len(tokens)), 4),
            "asr_words": sum(item["asr_words"] for item in audio),
            "asr_tokens_matched": len(anchors),
            "asr_tokens": len(hyp),
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "paragraphs": paragraphs,
        "words_format": "[part, start_s, end_s, anchor] per canonical token (preached.corpus.word_tokens order); "
                        "anchor 1 = exact match, 2 = fuzzy, 0 = interpolated",
        "words": words,
    }


def grouped_files(manifest: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for row in manifest:
        sid = row.get("canonical_sermon_id")
        if sid:
            groups.setdefault(sid, []).append(row)
    for rows in groups.values():
        rows.sort(key=lambda r: r["canonical_part"])
    return groups


def cmd_align(args: argparse.Namespace) -> None:
    sermons = load_sermons()
    groups = grouped_files(load_manifest())
    ALIGNED_DIR.mkdir(parents=True, exist_ok=True)
    ids = args.ids or sorted(groups)
    t0 = time.time()
    for sid in ids:
        t1 = time.time()
        result = align_sermon(sermons[sid], groups[sid])
        out = ALIGNED_DIR / f"{sid}.json"
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        tmp.replace(out)
        a = result["alignment"]
        flag = "  LOW" if a["coverage"] < COVERAGE_FLAG else ""
        print(f"{sid} {a['coverage']:.1%} anchored ({a['anchored_exact']}+{a['anchored_fuzzy']}/{a['canonical_words']})"
              f" {time.time() - t1:.1f}s{flag}", flush=True)
    print(f"aligned {len(ids)} sermons in {time.time() - t0:.0f}s -> {ALIGNED_DIR}")


# --------------------------------------------------------------------------
# chunks


def cmd_chunks(args: argparse.Namespace) -> None:
    """W1-B's chunks (same code, same corpus/chunk_config.json) with real times.

    chunk_id, text and word spans are exactly what ``corpus/chunk_sermons.py``
    produces, so eval quotes and the index key stay valid; only start_s,
    end_s and the audio fields change.
    """
    config = load_chunk_config(ROOT / "corpus" / "chunk_config.json")
    sermons = load_sermons()
    rows = []
    missing = []
    for sid, sermon in sorted(sermons.items()):
        path = ALIGNED_DIR / f"{sid}.json"
        if not path.exists():
            missing.append(sid)
            continue
        aligned = json.loads(path.read_text())
        words = aligned["words"]
        for chunk in chunk_sermon(sermon, config):
            part, start, end, share = span_times(words, chunk["word_start"], chunk["word_end"])
            audio = aligned["audio"][part]
            chunk.update(
                start_s=start, end_s=end,
                audio_url=audio["audio_url"], reader=audio["reader"], text_source="canonical",
                audio_file_id=audio["file_id"], alignment_anchored=share,
            )
            rows.append(chunk)
    if missing:
        raise SystemExit(f"not aligned yet: {missing[:5]}... run `align` first")
    write_jsonl(CHUNKS_ALIGNED, rows)
    shares = [row["alignment_anchored"] for row in rows]
    print(f"wrote {len(rows)} chunks to {CHUNKS_ALIGNED}; anchored share median "
          f"{statistics.median(shares):.3f}, chunks under 50% anchored: {sum(s < 0.5 for s in shares)}")


# --------------------------------------------------------------------------
# qa


def _window_words(transcript: dict, start: float, end: float, pad: float = 0.3) -> list[tuple[float, float, str]]:
    return [w for w in searchable_words(transcript) if start - pad <= w[0] < end + pad]


def _recall(canonical: str, words: list[tuple[float, float, str]]) -> float:
    want = Counter(tok for tok, _ in canonical_tokens(canonical))
    have = Counter(tok for tok, _ in asr_tokens([w for _, _, w in words]))
    return sum((want & have).values()) / max(1, sum(want.values()))


def cmd_qa(args: argparse.Namespace) -> None:
    manifest = load_manifest()
    groups = grouped_files(manifest)
    per_file = []
    recalls = []
    sentences = []
    transcripts: dict[str, dict] = {}
    for sid in sorted(groups):
        aligned = json.loads((ALIGNED_DIR / f"{sid}.json").read_text())
        for audio in aligned["audio"]:
            per_file.append({
                "file_id": audio["file_id"], "sermon_id": sid, "title": aligned["sermon_title"],
                "reader": audio["reader"], "coverage": audio["coverage"],
                "canonical_words": audio["canonical_words"], "asr_words": audio["asr_words"],
            })
        for p_index, paragraph in enumerate(aligned["paragraphs"]):
            for sentence in paragraph["sentences"]:
                if sentence["word_end"] - sentence["word_start"] >= 6:
                    sentences.append((sid, sentence, aligned["audio"][sentence["part"]]["file_id"]))
    # Timing sanity over every sentence: share of its words Whisper heard inside its window.
    for sid, sentence, file_id in sentences:
        transcript = transcripts.get(file_id) or transcripts.setdefault(file_id, load_transcript(file_id))
        recalls.append(_recall(sentence["text"], _window_words(transcript, sentence["start_s"], sentence["end_s"])))
    rng = random.Random(args.seed)
    spot = []
    for sid, sentence, file_id in rng.sample(sentences, 10):
        window = _window_words(transcripts[file_id], sentence["start_s"], sentence["end_s"])
        spot.append({
            "sermon_id": sid, "file_id": file_id, "start_s": sentence["start_s"], "end_s": sentence["end_s"],
            "anchored": sentence["anchored"], "canonical": sentence["text"],
            "whisper_window": " ".join(w for _, _, w in window),
            "whisper_first_last": [window[0][0], window[-1][1]] if window else None,
            "word_recall": round(_recall(sentence["text"], window), 3),
        })
    covs = [f["coverage"] for f in per_file]
    words_total = sum(f["canonical_words"] for f in per_file)
    summary = {
        "files": len(per_file),
        "coverage_mean": round(statistics.mean(covs), 4),
        "coverage_median": round(statistics.median(covs), 4),
        "coverage_min": min(covs),
        "coverage_words_weighted": round(sum(f["coverage"] * f["canonical_words"] for f in per_file) / words_total, 4),
        "files_under_90": [f for f in per_file if f["coverage"] < COVERAGE_FLAG],
        "sentences_checked": len(recalls),
        "sentence_window_recall_median": round(statistics.median(recalls), 3),
        "sentence_window_recall_p10": round(sorted(recalls)[len(recalls) // 10], 3),
        "sentences_recall_under_50": sum(r < 0.5 for r in recalls),
        "spot_check_seed": args.seed,
    }
    QA_JSON.write_text(json.dumps({"summary": summary, "per_file": per_file, "spot_check": spot}, indent=1, ensure_ascii=False))
    for f in sorted(per_file, key=lambda f: f["coverage"])[:10]:
        print(f"lowest: {f['file_id']:<18} {f['coverage']:.1%}  {f['title']}")
    print(json.dumps({k: v for k, v in summary.items() if k != "files_under_90"}, indent=1))
    print(f"files under 90%: {[f['file_id'] for f in summary['files_under_90']]}")
    for item in spot:
        print(f"\n[{item['sermon_id']} {item['start_s']:.2f}-{item['end_s']:.2f}s anchored {item['anchored']:.0%} "
              f"recall {item['word_recall']:.0%}]\n  CCEL:    {item['canonical']}\n  Whisper: {item['whisper_window']}")
    print(f"\nwrote {QA_JSON}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["map", "align", "chunks", "qa", "all"])
    parser.add_argument("--source-manifest", default=str(SOURCE_MANIFEST),
                        help="W1-A manifest (ingest/manifest/wesley.jsonl on feat/w1-ingest)")
    parser.add_argument("--ids", nargs="*", help="sermon ids for `align` (default: all)")
    parser.add_argument("--seed", type=int, default=20261030, help="spot-check sample seed")
    args = parser.parse_args()
    steps = ["map", "align", "chunks", "qa"] if args.step == "all" else [args.step]
    for step in steps:
        {"map": cmd_map, "align": cmd_align, "chunks": cmd_chunks, "qa": cmd_qa}[step](args)


if __name__ == "__main__":
    main()
