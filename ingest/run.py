"""Download + transcribe the Wesley manifest. Resumable and idempotent.

    uv run --extra transcribe ingest/run.py --limit 3     # first 3 manifest rows
    uv run --extra transcribe ingest/run.py --all         # everything
    uv run --extra transcribe ingest/run.py --ids wesley-s2-06 --redo
    uv run --extra transcribe ingest/run.py --library spurgeon --all   # see ingest/classics.py

Finished transcripts are skipped; each is written atomically, so a crash loses
at most the file in flight. Progress goes to $PREACHED_CACHE/transcripts/<library>/progress.log
(PREACHED_CACHE defaults to /cache).
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch  # noqa: E402
import manifest  # noqa: E402
import transcribe  # noqa: E402
from preached.libraries import PUBLIC_DOMAIN, is_public_domain  # noqa: E402

META_KEYS = [
    "id", "author", "work", "series", "sermon_number", "wesley_sermon_number", "kind",
    "title", "scripture", "scripture_text", "reader", "audio_url", "ia_url",
    "librivox_url", "text_source_url", "license_note",
]


def log(path: Path, msg: str) -> None:
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with path.open("a") as fh:
        fh.write(line + "\n")


class VramPeak:
    """Poll nvidia-smi for this process's GPU memory (MiB)."""

    def __init__(self) -> None:
        self.peak = 0
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        pid = str(os.getpid())
        while True:
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10,
                ).stdout
                for line in out.splitlines():
                    p, mem = (x.strip() for x in line.split(","))
                    if p == pid:
                        self.peak = max(self.peak, int(mem))
            except Exception:
                pass
            time.sleep(1)

    def take(self) -> int:
        p, self.peak = self.peak, 0
        return p


def out_path(row: dict, transcript_dir: Path) -> Path:
    manifest.check_name(row["id"], manifest.ID_RE)
    return manifest.safe_child(transcript_dir, f"{row['id']}.json")


def check_library(slug: str) -> str:
    """The slug, or SystemExit unless it is an allow-listed public-domain library."""
    if not is_public_domain(slug):
        raise SystemExit(
            f"error: --library {slug!r} refused: only public-domain libraries ({', '.join(PUBLIC_DOMAIN)}). "
            "For Wesley leave out --library."
        )
    return slug


@dataclass(frozen=True)
class LibraryPaths:
    """Where one library's manifest, audio, transcripts and progress log live."""

    manifest: Path
    audio_dir: Path
    transcript_dir: Path

    @property
    def log(self) -> Path:
        return self.transcript_dir / "progress.log"


def library_paths(slug: str | None = None) -> LibraryPaths:
    """Wesley's paths for None, else one allow-listed public-domain library's."""
    if slug is None:
        return LibraryPaths(manifest.MANIFEST, fetch.AUDIO_DIR, transcribe.TRANSCRIPT_DIR)
    check_library(slug)
    return LibraryPaths(
        manifest.MANIFEST.with_name(f"{slug}.jsonl"),
        fetch.CACHE_ROOT / "audio" / slug,
        transcribe.CACHE_ROOT / "transcripts" / slug,
    )


def voice_note(row: dict) -> str:
    if row.get("voice_note"):
        return row["voice_note"]
    return f"Read by LibriVox volunteer {row['reader']}; not {row['author']}'s voice."


def write_transcript(row: dict, segments: list[dict], info: dict, tr: transcribe.Transcriber, dest: Path) -> None:
    marks = transcribe.mark_boilerplate(segments, info["duration_s"])
    doc = {
        "meta": {
            **{k: row.get(k) for k in META_KEYS},
            "voice_note": voice_note(row),
            "duration_s": info["duration_s"],
            "language": info["language"],
            "gaps_filled": info["gaps_filled"],  # see Transcriber.fill_gaps
            "repaired_segments": info["repaired"],  # loop re-decodes, see repair_loops
            "model": tr.model_name,
            "model_repo": tr.model_repo,  # Hugging Face repo id (CTranslate2 weights)
            "model_revision": tr.revision,  # pinned commit
            "runtime": tr.runtime_info(),
            "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        },
        # Index only words with searchable_start <= start < searchable_end.
        **marks,
        "segments": segments,  # words: [[start, end, word], ...] seconds from file start
    }
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, dest)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sel = ap.add_mutually_exclusive_group(required=True)
    sel.add_argument("--all", action="store_true")
    sel.add_argument("--limit", type=int, help="first N manifest rows")
    sel.add_argument("--ids", nargs="+")
    ap.add_argument("--library", help=f"public-domain library ({', '.join(PUBLIC_DOMAIN)}): "
                    "ingest/manifest/<slug>.jsonl (default: the Wesley manifest)")
    ap.add_argument("--redo", action="store_true", help="retranscribe even if done")
    ap.add_argument("--download-only", action="store_true")
    args = ap.parse_args()

    paths = library_paths(args.library)
    rows = manifest.load(paths.manifest)
    if args.limit:
        rows = rows[: args.limit]
    elif args.ids:
        rows = [r for r in rows if r["id"] in set(args.ids)]
    paths.transcript_dir.mkdir(parents=True, exist_ok=True)
    todo = [r for r in rows if args.redo or not out_path(r, paths.transcript_dir).exists()]
    total_h = sum(r["duration_s"] for r in todo) / 3600
    log(paths.log, f"start: {len(rows)} selected, {len(rows) - len(todo)} already done, {len(todo)} to do ({total_h:.2f} h audio)")

    if args.download_only:
        for r in todo:
            fetch.ensure_audio(r, audio_dir=paths.audio_dir)
        log(paths.log, "downloads complete")
        return 0

    tr = transcribe.Transcriber()
    vram = VramPeak()
    failures = 0
    done_audio = 0.0
    t_run = time.time()
    # Download the next file while the GPU works on the current one.
    with ThreadPoolExecutor(max_workers=1) as pool:
        nxt = pool.submit(fetch.ensure_audio, todo[0], audio_dir=paths.audio_dir) if todo else None
        for i, row in enumerate(todo):
            try:
                path = nxt.result()
            except Exception as e:
                failures += 1
                log(paths.log, f"FAIL download {row['id']}: {e!r}")
                path = None
            nxt = pool.submit(fetch.ensure_audio, todo[i + 1], audio_dir=paths.audio_dir) if i + 1 < len(todo) else None
            if path is None:
                continue
            try:
                t0 = time.time()
                prompt = f"{row['work']}, by {row['author']}."
                segments, info = tr.transcribe(path, prompt)
                write_transcript(row, segments, info, tr, out_path(row, paths.transcript_dir))
                wall = time.time() - t0
                done_audio += info["duration_s"]
                rate = done_audio / (time.time() - t_run)
                left = sum(r["duration_s"] for r in todo[i + 1 :])
                log(
                    paths.log,
                    f"done {i + 1}/{len(todo)} {row['id']} audio={info['duration_s']:.0f}s wall={wall:.1f}s "
                    f"x{info['duration_s'] / wall:.0f} vram_peak={vram.take()}MiB "
                    f"setting={transcribe.LADDER[tr.rung]} eta={left / rate / 60:.0f}min"
                )
            except Exception as e:
                failures += 1
                log(paths.log, f"FAIL transcribe {row['id']}: {e!r}")
    wall = time.time() - t_run
    if todo:
        log(paths.log, f"finished: {len(todo) - failures}/{len(todo)} ok, {done_audio / 3600:.2f} h audio in "
            f"{wall / 3600:.2f} h wall = {done_audio / max(wall, 1e-9):.1f} audio-h per wall-h")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
