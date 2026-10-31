"""Publish-gate leak sweep: does anything an unpublished sermon holds reach a reader?

Builds two church library files through the real church path
(``align/asr_chunks.py``, Granite ONNX on CPU, the built-in privacy rules,
``--ack-review``) from public-domain Wesley transcripts relabelled as church
sermons, with made-up sample names spoken in them (no member data):

- ``hidden``: 6 approved sermons, 3 never approved, 2 approved but with
  coverage NULL (approved before the check existed), 1 approved with an open
  coverage span;
- ``clean``: the same 6 approved sermons only.

Then it asks both files the same things through ``app.server.App``: every
eval question plus words that occur only in the hidden sermons, in bm25,
dense and hybrid; ``/api/sermon`` for every id; ``/healthz``. A leak is

1. any hidden chunk id or sermon id in any response;
2. any response (``took_ms`` aside) that differs between the two files,
   so nothing about a hidden sermon can be inferred; ``pending_review`` on
   /healthz is the one intended difference (a count, never ids);
3. any served link whose seek lands within ``SEEK_SLACK_S`` after a flagged
   word end of a chunk the card's span reaches (``touches_flagged``).

Also prints the link margins: for every served link that starts after a
flagged word of its sermon, seek minus the nearest flagged word end before it.

    uv run python scripts/gate_leak_sweep.py --work /cache/w3-asr/gate-sweep
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("src", "align", ""):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

import numpy as np  # noqa: E402

import asr_chunks  # noqa: E402
from app.server import STATIC_DIR, App  # noqa: E402
from preached.search import SEEK_SLACK_S, Searcher, seek_time  # noqa: E402
from preached.store import open_readonly_or_exit  # noqa: E402
from preached.youtube.cli import main as youtube_main  # noqa: E402

MODEL = "granite-english-r2"
# Made-up sample names (AGENTS.md: no member data). Spoken twice in each sermon.
SAMPLE_NAMES = ["Gerald Fenwick", "Marjorie Quill", "Dorian Ashcombe", "Wilhelmina Thorne"]
STATES = (["approved"] * 6) + (["unapproved"] * 3) + (["coverage_null"] * 2) + ["coverage_open"]


def church_transcript(source: Path, index: int) -> dict:
    data = json.loads(source.read_text())
    sermon_id = f"church-{index:02d}"
    words = [w for seg in data["segments"] for w in seg["words"]]
    name = SAMPLE_NAMES[index % len(SAMPLE_NAMES)].split()
    # Two mentions, a third and two thirds in.
    for at in (len(words) // 3, 2 * len(words) // 3):
        for offset, part in enumerate(name):
            words[at + offset][2] = part
    return {
        "meta": {
            "id": sermon_id,
            "title": f"Sunday sermon {index}",
            "audio_url": f"https://archive.org/download/church-sample/{sermon_id}.mp3",
            "ia_url": "https://archive.org/details/church-sample",
            "duration_s": data["meta"]["duration_s"],
        },
        "searchable_start": data.get("searchable_start"),
        "searchable_end": data.get("searchable_end"),
        "segments": data["segments"],
    }


def build(root: Path, transcripts: list[Path], states: list[str], embed, privacy: Path) -> Path:
    root.mkdir(parents=True)
    audio = root / "audio"
    audio.mkdir()
    for path in transcripts:
        (audio / f"{path.stem}.wav").touch()  # the coverage stub never decodes it
    index = root / "church.sqlite"
    sink = StringIO()
    with redirect_stdout(sink), redirect_stderr(sink):
        asr_chunks.main(
            [*map(str, transcripts), "--out", str(root / "c.jsonl"), "--library", "church", "--privacy", str(privacy),
             "--index", str(index), "--audio-dir", str(audio)],
            embedder=embed,
            coverage=lambda *_a, **_k: [],
        )
        for path, state in zip(transcripts, states):
            if state != "unapproved":
                code = youtube_main(["--library", "church", "--ack-review", path.stem, "--privacy", str(privacy)],
                                    index_dir=root)
                if code != 0:
                    raise SystemExit(f"approval of {path.stem} failed:\n{sink.getvalue()[-2000:]}")
    import sqlite3

    writer = sqlite3.connect(index)
    for path, state in zip(transcripts, states):
        if state == "coverage_null":
            writer.execute("UPDATE videos SET coverage_gaps = NULL WHERE video_id = ?", (path.stem,))
        elif state == "coverage_open":
            writer.execute("UPDATE videos SET coverage_gaps = '[[100.0, 130.0]]' WHERE video_id = ?", (path.stem,))
    writer.commit()
    writer.close()
    return index


def make_app(index: Path, encode) -> App:
    connection = open_readonly_or_exit(index, check_same_thread=False)
    return App(connection=connection, searcher=Searcher(connection, model=MODEL), encode=encode, fallback_note=None,
               model_name=MODEL, hosts={"127.0.0.1"}, static_dir=STATIC_DIR, library="church")


SEEK = re.compile(r"(?:[?&]t=(\d+)s?|#t=([0-9.]+))")


def seek_of(result: dict) -> float | None:
    """Where a card's play link starts: its ``t=`` / ``#t=``, else the page's seek from ``start_s``."""
    if not result.get("audio_url"):
        return None
    match = SEEK.search(result["audio_url"])
    if match:
        return float(match.group(1) or match.group(2))
    return seek_time(result.get("start_s"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--work", type=Path, default=Path("/cache/w3-asr/gate-sweep"))
    parser.add_argument("--transcripts", type=Path, default=Path("/cache/transcripts/wesley"))
    args = parser.parse_args(argv)
    if args.work.exists():
        shutil.rmtree(args.work)
    src = args.work / "src"
    src.mkdir(parents=True)
    privacy = args.work / "privacy.toml"
    privacy.write_text("# built-in name rules only\n")

    sources = sorted(args.transcripts.glob("wesley-s1-*.json"))[1 : 1 + len(STATES)]
    paths = []
    for index, source in enumerate(sources, 1):
        path = src / f"church-{index:02d}.json"
        path.write_text(json.dumps(church_transcript(source, index)))
        paths.append(path)

    import os

    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    from preached.backends import load_embedder

    embedder = load_embedder(MODEL, "onnx", device="cpu", batch_size=8)

    def embed(titles, texts):
        return np.asarray(embedder.encode_documents(texts, titles), dtype=np.float32)

    def encode(query: str):
        return embedder.encode_queries([query])[0]

    approved = [p for p, s in zip(paths, STATES) if s == "approved"]
    hidden_ids = {p.stem for p, s in zip(paths, STATES) if s != "approved"}
    apps = {
        "hidden": make_app(build(args.work / "hidden", paths, STATES, embed, privacy), encode),
        "clean": make_app(build(args.work / "clean", approved, ["approved"] * len(approved), embed, privacy), encode),
    }
    hidden_conn = apps["hidden"].connection
    hidden_chunks = {r[0] for r in hidden_conn.execute(
        f"SELECT chunk_id FROM chunks WHERE video_id IN ({', '.join('?' * len(hidden_ids))})", sorted(hidden_ids))}

    # Words only the hidden sermons use: what a prober would try.
    def vocab(ids):
        rows = hidden_conn.execute(
            f"SELECT text FROM chunks WHERE video_id IN ({', '.join('?' * len(ids))})", sorted(ids))
        return {w for (text,) in rows for w in re.findall(r"[a-z]{6,}", text.lower())}

    only_hidden = sorted(vocab(hidden_ids) - vocab({p.stem for p in approved}))[:60]
    questions = [json.loads(line)["query"] for line in (ROOT / "eval" / "questions.jsonl").read_text().splitlines() if line.strip()]
    queries = [*questions, *only_hidden, "zzyzxnonsense", *SAMPLE_NAMES]

    leaks: list[str] = []
    responses = 0
    margins: list[float] = []
    links = 0
    for query in queries:
        for mode in ("bm25", "dense", "hybrid"):
            out = {}
            for name, app in apps.items():
                payload = app.search(query, 10, mode)
                payload.pop("took_ms")
                out[name] = payload
            responses += 1
            text = json.dumps(out["hidden"])
            for result in out["hidden"]["results"]:
                if result["chunk_id"] in hidden_chunks or result["sermon_id"] in hidden_ids:
                    leaks.append(f"hidden result: {query!r} {mode} {result['chunk_id']}")
            if any(i in text for i in hidden_ids):
                leaks.append(f"hidden id in response: {query!r} {mode}")
            if out["hidden"] != out["clean"]:
                leaks.append(f"response differs: {query!r} {mode}")
            for result in out["hidden"]["results"]:
                seek = seek_of(result)
                if seek is None:
                    continue
                flagged = hidden_conn.execute(
                    "SELECT flag_end_s, start_s FROM chunks WHERE sermon_id = ? AND flag_end_s IS NOT NULL",
                    (result["sermon_id"],)).fetchall()
                before = [seek - fe for fe, _ in flagged if fe <= seek]
                links += 1
                if before:
                    margins.append(min(before))
                end = result.get("end_s")
                for fe, start in flagged:
                    if fe > seek - SEEK_SLACK_S and (start is None or end is None or start < end):
                        leaks.append(f"link {result['audio_url']} seeks {seek - fe:+.2f}s after a flagged word end")
    for sermon_id in sorted({p.stem for p in paths}):
        a, b = (apps[n].sermon(sermon_id) for n in ("hidden", "clean"))
        responses += 1
        if sermon_id in hidden_ids and a is not None:
            leaks.append(f"/api/sermon served hidden {sermon_id}")
        if a != b:
            leaks.append(f"/api/sermon differs for {sermon_id}")
    health = {n: apps[n].health() for n in apps}
    responses += 1
    pending = (health["clean"].pop("pending_review"), health["hidden"].pop("pending_review"))
    if health["hidden"] != health["clean"]:
        leaks.append("/healthz differs beyond pending_review")

    print(json.dumps({
        "sermons": {"approved": len(approved), "hidden": len(hidden_ids)},
        "hidden_chunks": len(hidden_chunks),
        "queries": len(queries),
        "probe_words_only_in_hidden": len(only_hidden),
        "responses_compared": responses,
        "leaks": len(leaks),
        "pending_review_clean_vs_hidden": pending,
        "links_served": links,
        "links_after_a_flagged_word": len(margins),
        "margin_s": None if not margins else {
            "min": round(min(margins), 2),
            "p5": round(float(np.percentile(margins, 5)), 2),
            "median": round(float(np.median(margins)), 2),
        },
        "seek_slack_s": SEEK_SLACK_S,
    }, indent=1))
    for leak in leaks[:40]:
        print("LEAK", leak)
    return 1 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
