"""W1-A ingest: manifest/path safety, download hardening, transcript filters, WER.

No network and no GPU: downloads go through a fake opener.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingest"))
import fetch  # noqa: E402
import manifest  # noqa: E402
import run  # noqa: E402
import transcribe  # noqa: E402
import wer_check  # noqa: E402

BAD_FILE_NAMES = [
    "../x.mp3", "../../x.mp3", "/tmp/abs.mp3", "sub/dir/nested.mp3", "..\\x.mp3",
    "C:\\x.mp3", "C:x.mp3", "a\x00b.mp3", ".", "..", "", ".hidden.mp3", "a..b.mp3",
    "x.mp3\n", "-x.mp3", "x y.mp3", None, 5,
]
BAD_IDS = ["../x", "/abs", "a/b", "a\\b", "..", "", "Wesley-S1", "x.json", "a b", "x\n", None]


def _row(data: bytes = b"hello audio", **kw) -> dict:
    row = {
        "id": "wesley-s1-01",
        "file_name": "x.mp3",
        "audio_url": "https://archive.org/download/item/x.mp3",
        "size": len(data),
        "md5": hashlib.md5(data).hexdigest(),
    }
    row.update(kw)
    return row


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, url: str, status: int = 200):
        super().__init__(data)
        self.status = status
        self._url = url

    def geturl(self) -> str:
        return self._url


class PathSafetyTests(unittest.TestCase):
    def test_bad_file_names_rejected(self) -> None:
        for name in BAD_FILE_NAMES:
            with self.subTest(name=name), self.assertRaises(manifest.UnsafeRow):
                manifest.validate_row(_row(file_name=name))

    def test_bad_ids_rejected(self) -> None:
        for ident in BAD_IDS:
            with self.subTest(ident=ident), self.assertRaises(manifest.UnsafeRow):
                manifest.validate_row(_row(id=ident))

    def test_audio_path_stays_inside(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fetch, "AUDIO_DIR", Path(tmp) / "audio"):
            (Path(tmp) / "audio").mkdir()
            ok = fetch.audio_path(_row())
            self.assertEqual(ok.parent, (Path(tmp) / "audio").resolve())
            for name in BAD_FILE_NAMES:
                with self.subTest(name=name), self.assertRaises(manifest.UnsafeRow):
                    fetch.audio_path(_row(file_name=name))

    def test_symlinked_name_cannot_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "audio"
            base.mkdir()
            (base / "link.mp3").symlink_to(Path(tmp) / "outside.mp3")
            with self.assertRaises(manifest.UnsafeRow):
                manifest.safe_child(base, "link.mp3")

    def test_transcript_path_stays_inside(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run.out_path(_row(), Path(tmp)), Path(tmp).resolve() / "wesley-s1-01.json")
            for ident in BAD_IDS:
                with self.subTest(ident=ident), self.assertRaises(manifest.UnsafeRow):
                    run.out_path(_row(id=ident), Path(tmp))

    def test_committed_manifest_is_valid(self) -> None:
        rows = manifest.load()
        self.assertEqual(len(rows), 143)
        self.assertEqual(len({r["id"] for r in rows}), 143)
        self.assertEqual(len({r["file_name"] for r in rows}), 143)

    def test_load_rejects_a_bad_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "m.jsonl"
            p.write_text('{"id": "a", "file_name": "../x.mp3", "audio_url": '
                         '"https://archive.org/x", "size": 1, "md5": "' + "0" * 32 + '"}\n')
            with self.assertRaises(manifest.UnsafeRow):
                manifest.load(p)


class UrlTests(unittest.TestCase):
    GOOD = [
        "https://archive.org/download/item/x.mp3",
        "https://dn720708.ca.archive.org/0/items/item/x.mp3",
        "https://ia800.us.archive.org/1/items/item/x.mp3",
        "https://archive.org:443/download/x.mp3",
    ]
    BAD = [
        "http://archive.org/download/item/x.mp3",
        "file:///etc/passwd",
        "ftp://archive.org/x.mp3",
        "data:,hello",
        "https://evilarchive.org/x.mp3",
        "https://archive.org.evil.com/x.mp3",
        "https://user:pw@archive.org/x.mp3",
        "https://archive.org:8443/x.mp3",
        "https://archive.org:bad/x.mp3",
        "https://127.0.0.1/x.mp3",
        "//archive.org/x.mp3",
        None,
    ]

    def test_allowlist(self) -> None:
        for url in self.GOOD:
            with self.subTest(url=url):
                self.assertEqual(fetch.check_url(url), url)
        for url in self.BAD:
            with self.subTest(url=url), self.assertRaises(fetch.DownloadRefused):
                fetch.check_url(url)

    def test_redirect_handler_refuses_downgrade_and_offsite(self) -> None:
        handler = fetch.HttpsArchiveRedirects()
        req = urllib.request.Request("https://archive.org/download/item/x.mp3")
        for url in ["http://dn1.ca.archive.org/x.mp3", "https://example.com/x.mp3", "file:///etc/passwd"]:
            with self.subTest(url=url), self.assertRaises(fetch.DownloadRefused):
                handler.redirect_request(req, None, 302, "Found", {}, url)
        new = handler.redirect_request(req, None, 302, "Found", {}, "https://dn1.ca.archive.org/x.mp3")
        self.assertEqual(new.full_url, "https://dn1.ca.archive.org/x.mp3")

    def test_opener_has_no_plain_http_or_file_handler(self) -> None:
        schemes = {type(h).__name__ for h in fetch._OPENER.handlers}
        self.assertIn("HTTPSHandler", schemes)
        self.assertFalse(schemes & {"HTTPHandler", "FileHandler", "FTPHandler", "DataHandler"})


class DownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "audio"
        self.patches = [mock.patch.object(fetch, "AUDIO_DIR", self.dir),
                        mock.patch.object(fetch.time, "sleep", lambda s: None)]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def _serve(self, body: bytes, final_url: str = "https://dn1.ca.archive.org/x.mp3"):
        calls = []

        def fake_open(req, timeout):
            calls.append(req.full_url)
            return FakeResponse(body, final_url)

        return mock.patch.object(fetch, "_open", fake_open), calls

    def test_good_download(self) -> None:
        data = b"A" * 3_000_000
        patch, calls = self._serve(data)
        with patch:
            dest = fetch.ensure_audio(_row(data))
        self.assertEqual(dest.read_bytes(), data)
        self.assertEqual(len(calls), 1)
        self.assertFalse(list(self.dir.glob("*.part")))

    def test_oversize_body_is_cut_off_and_deleted(self) -> None:
        data = b"A" * 100
        patch, calls = self._serve(data + b"B" * 5_000_000)
        with patch, self.assertRaises(fetch.DownloadRefused):
            fetch.ensure_audio(_row(data))
        self.assertEqual(len(calls), 1, "a refused download is not retried")
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_final_url_downgrade_refused(self) -> None:
        data = b"hello"
        patch, _ = self._serve(data, final_url="http://dn1.ca.archive.org/x.mp3")
        with patch, self.assertRaises(fetch.DownloadRefused):
            fetch.ensure_audio(_row(data))
        self.assertFalse((self.dir / "x.mp3").exists())

    def test_unsafe_url_never_opened(self) -> None:
        patch, calls = self._serve(b"x")
        with tempfile.TemporaryDirectory() as tmp:
            secret = Path(tmp) / "s.txt"
            secret.write_bytes(b"x")
            for url in [secret.as_uri(), "http://127.0.0.1:9/x.mp3"]:
                with self.subTest(url=url), patch, self.assertRaises(fetch.DownloadRefused):
                    fetch.ensure_audio(_row(b"x", audio_url=url))
        self.assertEqual(calls, [])

    def test_md5_mismatch_retried_then_fails(self) -> None:
        patch, calls = self._serve(b"wrong")
        with patch, self.assertRaises(IOError):
            fetch.ensure_audio(_row(b"right"), retries=2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_existing_file_reused_only_if_md5_matches(self) -> None:
        data = b"good bytes"
        self.dir.mkdir(parents=True)
        (self.dir / "x.mp3").write_bytes(data)
        patch, calls = self._serve(data)
        with patch:
            fetch.ensure_audio(_row(data))
        self.assertEqual(calls, [])
        (self.dir / "x.mp3").write_bytes(b"BAD bytes!")  # same size, wrong content
        with patch:
            dest = fetch.ensure_audio(_row(data))
        self.assertEqual(len(calls), 1)
        self.assertEqual(dest.read_bytes(), data)

    def test_range_resume_counts_existing_bytes(self) -> None:
        data = b"0123456789"
        self.dir.mkdir(parents=True)
        (self.dir / "x.mp3.part").write_bytes(data[:4])

        def fake_open(req, timeout):
            self.assertEqual(req.headers.get("Range"), "bytes=4-")
            return FakeResponse(data[4:] + b"extra", "https://archive.org/x.mp3", status=206)

        with mock.patch.object(fetch, "_open", fake_open), self.assertRaises(fetch.DownloadRefused):
            fetch.ensure_audio(_row(data))
        self.assertEqual(list(self.dir.iterdir()), [])


def _words(text: str, start: float = 0.0, step: float = 0.4) -> list[list]:
    return [[round(start + i * step, 2), round(start + i * step + 0.3, 2), w] for i, w in enumerate(text.split())]


class FilterTests(unittest.TestCase):
    def test_wesley_number(self) -> None:
        self.assertIsNone(manifest.wesley_number("s1", 0))
        self.assertEqual(manifest.wesley_number("s1", 1), 1)
        self.assertEqual(manifest.wesley_number("s1", 40), 40)
        self.assertEqual(manifest.wesley_number("s1", 41), 40)  # Christian Perfection, part 2
        self.assertEqual(manifest.wesley_number("s1", 54), 53)
        self.assertEqual(manifest.wesley_number("s2", 1), 54)
        self.assertEqual(manifest.wesley_number("s2", 55), 108)
        self.assertEqual(manifest.wesley_number("s3to5", 1), 109)
        self.assertEqual(manifest.wesley_number("s3to5", 33), 141)

    def test_has_loop_keeps_holy_holy_holy(self) -> None:
        self.assertFalse(transcribe.has_loop(_words("Holy, holy, holy, Lord God Almighty")))
        self.assertFalse(transcribe.has_loop(_words("Lord, Lord, have we not prophesied")))
        self.assertTrue(transcribe.has_loop(_words("Toe, toe, toe, toe, toe")))
        self.assertTrue(transcribe.has_loop(_words("the law the law the law the law of God")))

    def test_collapse_loops_keeps_two_repeats(self) -> None:
        out = transcribe.collapse_loops(_words("he said toe toe toe toe toe toe and then"))
        self.assertEqual([w[2] for w in out], ["he", "said", "toe", "toe", "and", "then"])
        out = transcribe.collapse_loops(_words("a b a b a b a b c"))
        self.assertEqual([w[2] for w in out], ["a", "b", "a", "b", "c"])
        same = _words("Holy, holy, holy, Lord")
        self.assertEqual(transcribe.collapse_loops(same), same)

    def test_hallucinated(self) -> None:
        def seg(words, nsp=0.1, lp=-0.3):
            return {"words": words, "_nsp": nsp, "_lp": lp}

        normal = _words("And this is the word of the Lord.", step=0.35)
        self.assertFalse(transcribe._hallucinated(seg(normal)))
        squeezed = _words("We'll be right back.", step=0.05)  # 4 words in ~0.45 s
        self.assertTrue(transcribe._hallucinated(seg(squeezed)))
        self.assertTrue(transcribe._hallucinated(seg(normal, nsp=0.9)))
        self.assertTrue(transcribe._hallucinated(seg(normal, lp=-1.5)))
        fast = [[i * 0.1, i * 0.1 + 0.05, "w"] for i in range(20)]  # 10 words/s
        self.assertTrue(transcribe._hallucinated(seg(fast)))

    def _segments(self, text: str, start: float, step: float = 0.4) -> list[dict]:
        words = _words(text, start, step)
        return [{"start": words[0][0], "end": words[-1][1], "text": text, "words": words}]

    def test_mark_boilerplate_intro_and_outro(self) -> None:
        intro = self._segments("Sermon 20 of Sermons on Several Occasions. This is a LibriVox recording. "
                               "All LibriVox recordings are in the public domain. Recording by Bill Mosley.", 1.0)
        body = self._segments("Of Hell. These shall go away into everlasting punishment. " * 20, 30.0)
        outro = self._segments("Amen. End of section twenty. Recording by Bill Mosley.", 990.0)
        segs = intro + body + outro
        marks = transcribe.mark_boilerplate(segs, 1000.0)
        self.assertEqual(marks["searchable_start"], body[0]["start"])
        self.assertTrue(marks["boilerplate_intro"].endswith("Recording by Bill Mosley."))
        self.assertTrue(marks["boilerplate_outro"].startswith("End of section"))
        self.assertTrue(intro[0].get("boilerplate"))
        self.assertFalse(body[0].get("boilerplate"))
        # "Amen." stays searchable: the outro starts at "End of section".
        self.assertEqual(marks["searchable_end"], outro[0]["words"][0][1])

    def test_mark_boilerplate_nothing_to_mark(self) -> None:
        segs = self._segments("By grace are ye saved through faith.", 5.0)
        marks = transcribe.mark_boilerplate(segs, 100.0)
        self.assertEqual((marks["boilerplate_intro"], marks["boilerplate_outro"]), ("", ""))
        self.assertEqual(marks["searchable_start"], 5.0)
        empty = transcribe.mark_boilerplate([], 50.0)
        self.assertEqual((empty["searchable_start"], empty["searchable_end"]), (0.0, 50.0))


class WerTests(unittest.TestCase):
    def test_norm(self) -> None:
        self.assertEqual(wer_check.norm("Favor, honor[12] and 3 well-being!"),
                         ["favour", "honour", "and", "three", "well", "being"])

    def test_wer(self) -> None:
        ref = "by grace are ye saved through faith".split()
        self.assertEqual(wer_check.wer(ref, ref), (0.0, 0))
        hyp = "sermon one by grace are we saved through faith and so on".split()
        rate, errs = wer_check.wer(ref, hyp)  # free leading/trailing hyp words
        self.assertEqual(errs, 1)  # ye -> we
        self.assertAlmostEqual(rate, 1 / 7)
        _, errs = wer_check.wer(ref, "by grace are saved through faith".split())
        self.assertEqual(errs, 1)  # deletion
        _, errs = wer_check.wer(ref, [])
        self.assertEqual(errs, len(ref))


class CcelShaTests(unittest.TestCase):
    """PR #5 re-review: a missing sha256_text is fatal, not a skipped check."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.text = self.dir / "sermons.txt"
        self.text.write_text("First Series\n     ___ body")
        self.catalog = self.dir / "catalog.json"
        self.good = hashlib.sha256(self.text.read_bytes()).hexdigest()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def patched(self):
        return (
            mock.patch.object(manifest, "SERMONS_TEXT", self.text),
            mock.patch.object(manifest, "catalog_path", lambda: self.catalog),
        )

    def run_ccel(self) -> str:
        a, b = self.patched()
        with a, b:
            return manifest.ccel_text()

    def test_matching_sha_is_read(self) -> None:
        self.catalog.write_text(json.dumps({"sha256_text": self.good}))
        self.assertIn("body", self.run_ccel())

    def test_wrong_sha_is_refused(self) -> None:
        self.catalog.write_text(json.dumps({"sha256_text": "0" * 64}))
        with self.assertRaisesRegex(RuntimeError, "!="):
            self.run_ccel()

    def test_missing_or_empty_sha_is_fatal(self) -> None:
        for body in ({}, {"sha256_text": ""}, {"sha256_text": None}):
            with self.subTest(body=body):
                self.catalog.write_text(json.dumps(body))
                with self.assertRaisesRegex(RuntimeError, "no sha256_text"):
                    self.run_ccel()

    def test_missing_catalog_is_fatal(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "missing"):
            self.run_ccel()

    def test_corpus_fetch_refuses_missing_sha_but_accept_new_text_still_works(self) -> None:
        from preached import corpus

        self.catalog.write_text(json.dumps({"work": "x"}))
        with mock.patch.object(corpus, "CORPUS_DIR", self.dir), \
                mock.patch.object(corpus, "SERMONS_TEXT", self.text), \
                mock.patch.object(corpus, "catalog_path", lambda: self.catalog):
            with self.assertRaisesRegex(RuntimeError, "no sha256_text"):
                corpus.fetch_corpus()
            # The escape hatch skips the check; stop right after it.
            with mock.patch.object(corpus, "NUMBER_INDEX_HTML", self.dir / "idx.html"), \
                    mock.patch.object(corpus, "download", side_effect=RuntimeError("past the check")):
                with self.assertRaisesRegex(RuntimeError, "past the check"):
                    corpus.fetch_corpus(accept_new_text=True)


class ModelBinShaTests(unittest.TestCase):
    """Optional runtime pin of Whisper's model.bin (tests use a tiny fake file)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "model.bin"
        self.path.write_bytes(b"fake weights")
        self.good = hashlib.sha256(b"fake weights").hexdigest()
        transcribe._VERIFIED.clear()

    def tearDown(self) -> None:
        self._tmp.cleanup()
        transcribe._VERIFIED.clear()

    def test_match_is_verified_once_per_process(self) -> None:
        self.assertTrue(transcribe.verify_model_bin(self.path, self.good, env={}))
        with mock.patch.object(Path, "open", side_effect=AssertionError("hashed twice")):
            self.assertTrue(transcribe.verify_model_bin(self.path, self.good, env={}))

    def test_mismatch_is_refused(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Refusing to load"):
            transcribe.verify_model_bin(self.path, "0" * 64, env={})

    def test_modified_file_is_rechecked(self) -> None:
        transcribe.verify_model_bin(self.path, self.good, env={})
        self.path.write_bytes(b"tampered weights")
        with self.assertRaises(RuntimeError):
            transcribe.verify_model_bin(self.path, self.good, env={})

    def test_opt_out_and_absent_file_skip(self) -> None:
        self.assertFalse(transcribe.verify_model_bin(self.path, "0" * 64, env={"PREACHED_SKIP_MODEL_SHA": "1"}))
        self.assertFalse(transcribe.verify_model_bin(self.path.with_name("none.bin"), self.good, env={}))

    def test_missing_file_is_an_error_when_required(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "missing"):
            transcribe.verify_model_bin(self.path.with_name("none.bin"), self.good, env={}, required=True)
        # The opt-out still wins.
        self.assertFalse(transcribe.verify_model_bin(
            self.path.with_name("none.bin"), self.good, env={"PREACHED_SKIP_MODEL_SHA": "1"}, required=True))

    def test_pin_matches_the_report(self) -> None:
        report = (Path(__file__).resolve().parents[1] / "reports" / "W1-A.md").read_text()
        self.assertIn(transcribe.MODEL_BIN_SHA256, report)


class TranscriberLoadTests(unittest.TestCase):
    """PR #9 should-fix: `_load` sets the model only after the post-load hash
    check, and a missing model.bin after loading is refused (fake faster_whisper,
    tiny fake weights; no GPU, no real model)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.bin = Path(self._tmp.name) / "model.bin"
        self.good = hashlib.sha256(b"fake weights").hexdigest()
        self.loads = 0
        self.content = b"fake weights"  # what a "download" writes; None = writes nothing
        test = self

        class WhisperModel:
            def __init__(self, *args, **kwargs):
                test.loads += 1
                if test.content is not None and not test.bin.exists():
                    test.bin.write_bytes(test.content)

        class BatchedInferencePipeline:
            def __init__(self, model):
                self.model = model

        fake = type(sys)("faster_whisper")
        fake.WhisperModel = WhisperModel
        fake.BatchedInferencePipeline = BatchedInferencePipeline
        env = {k: v for k, v in os.environ.items() if k != "PREACHED_SKIP_MODEL_SHA"}
        for patcher in (
            mock.patch.dict(sys.modules, {"faster_whisper": fake}),
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(transcribe, "snapshot_model_bin", lambda repo, rev: self.bin),
            mock.patch.object(transcribe, "MODEL_BIN_SHA256", self.good),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        transcribe._VERIFIED.clear()
        self.addCleanup(transcribe._VERIFIED.clear)
        self.t = transcribe.Transcriber.__new__(transcribe.Transcriber)
        self.t.model_name, self.t.model_repo, self.t.revision = (
            transcribe.MODEL, transcribe.MODEL_REPO, transcribe.MODEL_REVISION)
        self.t.rung, self.t._model, self.t._pipe = 0, None, None

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_good_download_loads(self) -> None:
        self.t._load()
        self.assertIsNotNone(self.t._model)
        self.assertIs(self.t._pipe.model, self.t._model)

    def test_bad_download_never_sets_model_and_retry_rechecks(self) -> None:
        self.content = b"corrupt weights"
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, "Refusing to load"):
                self.t._load()
            self.assertIsNone(self.t._model)
            self.assertIsNone(self.t._pipe)
        # The retry re-verified: the now-cached bad file was refused before loading.
        self.assertEqual(self.loads, 1)

    def test_missing_model_bin_after_load_is_refused(self) -> None:
        self.content = None  # weights "live in another cache": nothing to hash
        with self.assertRaisesRegex(RuntimeError, "missing"):
            self.t._load()
        self.assertIsNone(self.t._model)

    def test_opt_out_loads_without_model_bin(self) -> None:
        self.content = None
        with mock.patch.dict(os.environ, {"PREACHED_SKIP_MODEL_SHA": "1"}):
            self.t._load()
        self.assertIsNotNone(self.t._model)

    def test_unpinned_repo_is_not_checked(self) -> None:
        self.content = None
        self.t.revision = "f" * 40
        self.t._load()
        self.assertIsNotNone(self.t._model)


if __name__ == "__main__":
    unittest.main()
