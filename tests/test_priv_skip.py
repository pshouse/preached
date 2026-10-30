"""W3-PRIV-SKIP: announcements, prayer requests and testimonies are never indexed.

Invented service transcripts; every name and marker word below is made up.
Lowercase marker words ("marigoldsupper") are not names, so redaction keeps
them: if one reaches the index, the exclusion leaked.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from preached import skip
from preached.exclusions import words_file
from preached.search import Searcher
from preached.store import open_readonly

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_privacy_wire import CHANNEL, FILLER, ID_A, Base, embedder, words_for  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

ANNOUNCE = (
    "Good morning church, we have a few announcements. The potluck is Wednesday at 6:30 in the fellowship hall, "
    "so bring a marigoldsupper dish. Sign up in the lobby after the service. "
)
PRAYER = (
    "Before we go on, please be praying for the Ashcombe family. Their son had surgery this week and the "
    "larkspurward nurses are hopeful. Keep them in your prayers. "
)
TESTIMONY = (
    "Now Dorinda is going to share with us. I want to share what God did in my life. Years ago the copperkettle "
    "years were hard and I had nothing. My family prayed for me. Then I got saved and everything changed. "
    "Thank you for sharing that. "
)
SERMON_START = "Open your Bibles to Psalm 23. "
REVIEWER_MISS = "Our velvetlantern sentence is here. "
CLOSING = "The Lord bless you and keep you. Remember the quillbasket drive on Saturday. "
MARKERS = ("marigoldsupper", "larkspurward", "copperkettle", "quillbasket")
SERVICE = (
    ANNOUNCE + SERMON_START + FILLER * 12 + PRAYER + FILLER * 12 + TESTIMONY + FILLER * 6 + REVIEWER_MISS
    + FILLER * 12 + "zephyrgrace ends here. " + CLOSING
)


class DetectorTests(unittest.TestCase):
    def excluded_text(self, text: str) -> list[str]:
        words = text.split()
        return [" ".join(words[s.start : s.end]) for s in skip.propose(words)]

    def test_each_category_is_proposed(self) -> None:
        words = SERVICE.split()
        stretches = skip.propose(words)
        joined = [" ".join(words[s.start : s.end]) for s in stretches]
        for marker in MARKERS:
            self.assertTrue(any(marker in text for text in joined), marker)
        self.assertNotIn("velvetlantern", " ".join(joined))
        self.assertNotIn("zephyrgrace", " ".join(joined))
        categories = {s.category for s in stretches}
        self.assertTrue({"announcements", "prayer", "testimony"} <= categories, categories)
        for s in stretches:
            self.assertTrue(s.cues or s.reasons != ["cue"])
            for cue, word in s.cues:
                self.assertTrue(s.start <= word < s.end, (cue, word))

    def test_position_cues(self) -> None:
        pre = "Welcome everybody, it's good to see the kids here. " + SERMON_START + FILLER * 20
        stretches = skip.propose(pre.split())
        self.assertEqual(stretches[0].start, 0)
        self.assertIn("before the sermon proper", stretches[0].reasons)
        tail = FILLER * 20 + "Go in peace. And thank the welcome team."
        stretches = skip.propose(tail.split())
        self.assertIn("after the benediction", stretches[-1].reasons)
        self.assertEqual(stretches[-1].end, len(tail.split()))

    def test_sermon_language_is_kept(self) -> None:
        for text in (
            FILLER * 10,
            "The testimony of Scripture is clear. Jesus rose on the first day of the week. " + FILLER * 5,
            "We pray because God hears. Prayer is not a performance. " + FILLER * 5,
        ):
            self.assertEqual(self.excluded_text(text), [], text)

    def test_deterministic_and_no_model(self) -> None:
        words = SERVICE.split()
        self.assertEqual([s.as_dict() for s in skip.propose(words)], [s.as_dict() for s in skip.propose(list(words))])
        source = (ROOT / "src" / "preached" / "skip.py").read_text()
        imports = {line.split()[1].split(".")[0] for line in source.splitlines() if line.startswith(("import ", "from "))}
        self.assertEqual(imports, {"__future__", "re", "dataclasses", "typing"})


class ImportTests(Base):
    """YouTube import of one invented service with every category in it."""

    def setUp(self) -> None:
        super().setUp()
        self.words = words_for(SERVICE)

    def run_import(self, extra: list[str] | None = None):
        from datetime import date

        from preached.youtube.listing import Video

        video = Video(ID_A, "Sunday service", 400, date(2024, 6, 2), f"https://www.youtube.com/watch?v={ID_A}")
        return self.cli(
            [CHANNEL, "--library", "wire", *(extra or [])],
            lister=lambda _url: [video],
            metadata=lambda v: {"title": v.title, "duration": 400, "upload_date": "20240602"},
            downloader=lambda v, dest: dest / f"{v.id}.m4a",
            transcriber=lambda path: self.words,
            embedder=embedder,
        )

    def lines(self) -> list[dict]:
        return [json.loads(line) for line in self.review_file(ID_A).read_text().splitlines()]

    def write_lines(self, lines: list[dict]) -> None:
        self.review_file(ID_A).write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines))

    def raw_index(self) -> bytes:
        data = self.index.read_bytes()
        wal = Path(f"{self.index}-wal")
        return data + (wal.read_bytes() if wal.exists() else b"")

    def ack(self, **kwargs):
        return self.cli(["--library", "wire", "--ack-review", ID_A], **kwargs)

    def rows(self):
        connection = open_readonly(self.index)
        self.addCleanup(connection.close)
        return connection, list(connection.execute("SELECT * FROM chunks WHERE video_id = ? ORDER BY word_start", (ID_A,)))

    def test_nothing_excluded_reaches_the_index_or_the_console(self) -> None:
        code, out, err = self.run_import()
        self.assertEqual(code, 0, err)
        raw = self.raw_index()
        for marker in MARKERS:
            self.assertNotIn(marker.encode(), raw)
            self.assertNotIn(marker, out + err)
        self.assertIn(b"velvetlantern", raw)
        self.assertIn(b"zephyrgrace", raw)
        self.assertIn("excluded stretches", err)
        excludes = [line for line in self.lines() if line.get("field") == "exclude"]
        self.assertTrue({"announcements", "prayer", "testimony"} <= {line["category"] for line in excludes})
        # Approved as proposed: still nothing excluded is searchable; vectors match chunks.
        code, _out, err = self.ack(embedder=_no_embedder)
        self.assertEqual(code, 0, err)
        connection, rows = self.rows()
        searcher = Searcher(connection, gated=True)
        self.assertTrue(searcher.bm25("zephyrgrace", 5))
        for marker in MARKERS:
            self.assertEqual(searcher.bm25(marker, 5), [])
        vectors = connection.execute("SELECT count(*) FROM embeddings").fetchone()[0]
        self.assertEqual(vectors, len(rows))
        self.assertFalse(words_file(self.review_file(ID_A)).exists())

    def test_chunks_are_cut_at_every_boundary(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        excludes = [line for line in self.lines() if line.get("field") == "exclude"]
        _, rows = self.rows()
        for line in excludes:
            for row in rows:
                self.assertFalse(row["word_start"] < line["end_word"] and row["word_end"] > line["start_word"], (dict(row), line))
                self.assertFalse(row["start_s"] < line["end_s"] and row["end_s"] > line["start_s"], (dict(row), line))
        # Some chunk ends on the word just before a stretch, and one starts right after it.
        prayer = next(line for line in excludes if line["category"] == "prayer")
        self.assertIn(prayer["start_word"], {row["word_end"] for row in rows})
        self.assertIn(prayer["end_word"], {row["word_start"] for row in rows})
        expected = " ".join(w.text for w in self.words[rows[0]["word_start"] : rows[0]["word_end"]])
        self.assertEqual(rows[0]["text"], expected)

    def test_reviewer_added_stretch_is_excluded(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        self.assertIn(b"velvetlantern", self.raw_index())
        index = next(i for i, w in enumerate(self.words) if w.text == "velvetlantern")
        lines = self.lines()
        insert = next(i for i, line in enumerate(lines) if line.get("field") == "exclude")
        lines.insert(insert, {"field": "exclude", "start_s": self.words[index - 1].start, "end_s": self.words[index + 3].end, "note": "reviewer"})
        self.write_lines(lines)
        code, out, err = self.ack(embedder=embedder)
        self.assertEqual(code, 0, err)
        raw = self.raw_index()
        self.assertNotIn(b"velvetlantern", raw)
        for marker in MARKERS:
            self.assertNotIn(marker.encode(), raw)
        self.assertNotIn("velvetlantern", out + err)
        connection, rows = self.rows()
        searcher = Searcher(connection, gated=True)
        self.assertEqual(searcher.bm25("velvetlantern", 5), [])
        self.assertTrue(searcher.bm25("zephyrgrace", 5))  # approved and served
        self.assertEqual(connection.execute("SELECT count(*) FROM embeddings").fetchone()[0], len(rows))
        for row in rows:  # cut at the new boundary too
            self.assertFalse(row["word_start"] < index + 4 and row["word_end"] > index - 1)
        self.assertFalse(words_file(self.review_file(ID_A)).exists())

    def test_widened_stretch_is_excluded(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        lines = self.lines()
        prayer = next(line for line in lines if line.get("field") == "exclude" and line["category"] == "prayer")
        before = prayer["start_word"]
        prayer["start_word"] = before - 10
        self.write_lines(lines)
        self.assertEqual(self.ack(embedder=embedder)[0], 0)
        _, rows = self.rows()
        for row in rows:
            self.assertFalse(row["word_start"] < prayer["end_word"] and row["word_end"] > before - 10)

    def test_narrowing_or_removing_is_refused(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        original = self.review_file(ID_A).read_text()
        lines = self.lines()
        narrowed = [dict(line) for line in lines]
        stretch = next(line for line in narrowed if line.get("field") == "exclude")
        stretch["end_word"] -= 3
        stretch["end_s"] = stretch["start_s"] + 0.1
        self.write_lines(narrowed)
        code, _out, err = self.ack(embedder=embedder)
        self.assertEqual(code, 1)
        self.assertIn("not narrowed or removed", err)
        self.write_lines([line for line in lines if line.get("field") != "exclude"])
        self.assertEqual(self.ack(embedder=embedder)[0], 1)
        self.review_file(ID_A).write_text(original)
        self.assertEqual(self.ack(embedder=_no_embedder)[0], 0)

    def test_editing_after_approval_is_refused(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        self.assertEqual(self.ack(embedder=_no_embedder)[0], 0)
        lines = self.lines()
        lines.append({"field": "exclude", "start_word": 0, "end_word": 5})
        self.write_lines(lines)
        code, _out, err = self.ack(embedder=embedder)
        self.assertEqual(code, 1)
        self.assertIn("changed after approval", err)
        _, rows = self.rows()
        self.assertTrue(rows)

    def test_other_lines_and_the_words_file_are_covered(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        added = {"field": "exclude", "start_word": 0, "end_word": 5}
        original = self.lines()
        lines = [dict(line) for line in original] + [added]
        lines[0]["stored"] = "Edited title"
        self.write_lines(lines)
        code, _out, err = self.ack(embedder=embedder)
        self.assertEqual(code, 1)
        self.assertIn("outside its exclude lines", err)
        self.write_lines([*original, added])
        words = words_file(self.review_file(ID_A))
        words.write_text(words.read_text().replace("zephyrgrace", "zephyrgrape"))
        code, _out, err = self.ack(embedder=embedder)
        self.assertEqual(code, 1)
        self.assertIn("does not match", err)

    def test_bad_exclude_lines_are_refused(self) -> None:
        self.assertEqual(self.run_import()[0], 0)
        lines = self.lines()
        for bad in ({"field": "exclude"}, {"field": "exclude", "start_word": 5, "end_word": 2},
                    {"field": "exclude", "start_word": 0, "end_word": 10 ** 9}, {"field": "exclude", "start_s": "x", "end_s": 3}):
            self.write_lines([*lines, bad])
            self.assertEqual(self.ack(embedder=embedder)[0], 1, bad)
        _, rows = self.rows()
        self.assertTrue(rows)

    def test_review_and_words_files_are_private(self) -> None:
        import stat

        self.assertEqual(self.run_import()[0], 0)
        for path in (self.review_file(ID_A), words_file(self.review_file(ID_A))):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        text = words_file(self.review_file(ID_A)).read_text()
        for marker in MARKERS:
            self.assertNotIn(marker, text)


def _no_embedder(titles, texts):
    raise AssertionError("an unchanged review must not re-embed")


class AsrPathTests(unittest.TestCase):
    """align/asr_chunks.py: church sermons get the same exclusions; Wesley does not."""

    def setUp(self) -> None:
        import tempfile
        from unittest.mock import patch

        sys.path.insert(0, str(ROOT / "align"))
        self.addCleanup(sys.path.remove, str(ROOT / "align"))
        import asr_chunks

        self.module = asr_chunks
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = {k: v for k, v in os.environ.items() if k not in ("PREACHED_PRIVACY", "PREACHED_FLAGGED_AUDIO")}
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        words = words_for(SERVICE)
        self.words = words
        self.doc = {"meta": {"id": "church-1", "title": "Sunday"}, "segments": [{"words": [[w.start, w.end, w.text] for w in words]}]}
        self.path = self.root / "church-1.json"
        self.path.write_text(json.dumps(self.doc))
        self.toml = self.root / "privacy.toml"
        self.toml.write_text("")

    def main(self, argv):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.module.main([str(self.path), "--out", str(self.root / "c.jsonl"), *argv], embedder=embedder)
        return out.getvalue() + err.getvalue()

    def test_church_asr_excludes_and_reviewer_additions_apply(self) -> None:
        index = self.root / "church.sqlite"
        log = self.main(["--library", "church", "--privacy", str(self.toml), "--index", str(index)])
        text = (self.root / "c.jsonl").read_text()
        for marker in MARKERS:
            self.assertNotIn(marker, text)
            self.assertNotIn(marker, log)
            self.assertNotIn(marker.encode(), index.read_bytes())
        rows = [json.loads(line) for line in text.splitlines()]
        self.assertEqual([r["chunk_id"] for r in rows], [f"asr:church-1-c{i:04d}" for i in range(len(rows))])
        spans = [(r["word_start"], r["word_end"]) for r in rows]
        self.assertEqual(spans, sorted(spans))
        review = self.root / "church" / "review" / "church-1.review.jsonl"
        lines = [json.loads(line) for line in review.read_text().splitlines()]
        excludes = [line for line in lines if line.get("field") == "exclude"]
        for line in excludes:
            for row in rows:
                self.assertFalse(row["start_s"] < line["end_s"] and row["end_s"] > line["start_s"])
        index_of = next(i for i, w in enumerate(self.words) if w.text == "velvetlantern")
        lines.append({"field": "exclude", "start_word": index_of - 1, "end_word": index_of + 4})
        review.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines))
        from preached.youtube.cli import main as youtube_main

        with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as err:
            code = youtube_main(["--library", "church", "--ack-review", "church-1", "--privacy", str(self.toml)], index_dir=self.root, embedder=embedder)
        self.assertEqual(code, 0, err.getvalue())
        raw = index.read_bytes() + (Path(f"{index}-wal").read_bytes() if Path(f"{index}-wal").exists() else b"")
        self.assertNotIn(b"velvetlantern", raw)
        connection = open_readonly(index)
        self.addCleanup(connection.close)
        searcher = Searcher(connection, gated=True)
        self.assertTrue(searcher.bm25("zephyrgrace", 5))
        self.assertEqual(searcher.bm25("velvetlantern", 5), [])
        audio = {row[0] for row in connection.execute("SELECT text_source FROM chunks")}
        self.assertEqual(audio, {"asr"})

    def test_wesley_keeps_every_word(self) -> None:
        doc = dict(self.doc, meta={"id": "wesley-001", "title": "Sermon"})
        rows = self.module.asr_chunks(doc, self.module.load_chunk_config(ROOT / "corpus" / "chunk_config.json"))
        text = " ".join(r["text"] for r in rows)
        for marker in MARKERS:
            self.assertIn(marker, text)
        self.assertNotIn("video_id", rows[0])


class ClassicsUntouchedTests(unittest.TestCase):
    def test_build_library_does_not_use_the_detector(self) -> None:
        for path in ("search/build_library.py", "src/preached/libraries.py", "ingest/run.py"):
            source = (ROOT / path).read_text()
            self.assertNotIn("preached.skip", source)
            self.assertNotIn("exclusions", source)


if __name__ == "__main__":
    unittest.main()
