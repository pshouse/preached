"""#12 must-fix 3: review files never follow a symlink (write_private_review and asr_chunks).

The CTO's repro: write_private_review resolved the path first, so a symlink
planted at the review path replaced the victim file and chmodded the victim's
directory 0700. Every name below is invented.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "align") not in sys.path:
    sys.path.insert(0, str(ROOT / "align"))

import asr_chunks  # noqa: E402
from preached.privacy import _open_private_dir, read_private_file  # noqa: E402
from preached.youtube.pipeline import write_private_review  # noqa: E402
from test_privacy_wire import FILLER, embedder, words_for  # noqa: E402
from coverage_stub import stub_audio

ITEMS = [{"text": "Invented Person", "reason": "test"}]


class Victim:
    """A file and its directory owned by the user, with modes that must not change."""

    def __init__(self, root: Path) -> None:
        self.dir = root / "victim-dir"
        self.dir.mkdir()
        os.chmod(self.dir, 0o755)
        self.file = self.dir / "victim.txt"
        self.file.write_text("keep me\n")
        os.chmod(self.file, 0o644)
        self.mtimes = (self.file.stat().st_mtime_ns, self.dir.stat().st_mtime_ns)

    def untouched(self, case: unittest.TestCase) -> None:
        case.assertEqual((self.file.stat().st_mtime_ns, self.dir.stat().st_mtime_ns), self.mtimes)
        case.assertEqual(self.file.read_text(), "keep me\n")
        case.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o644)
        case.assertEqual(stat.S_IMODE(self.dir.stat().st_mode), 0o755)
        case.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["victim.txt"])


class WritePrivateReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.victim = Victim(self.root)

    def write(self, path: Path):
        with redirect_stdout(StringIO()):
            return write_private_review(ITEMS, path)

    def test_symlink_at_the_file_is_replaced_not_followed(self) -> None:
        review = self.root / "index" / "church" / "review"
        review.mkdir(parents=True, mode=0o700)
        link = review / "s1.review.jsonl"
        link.symlink_to(self.victim.file)
        count, digest = self.write(link)
        self.assertEqual(count, 1)
        self.victim.untouched(self)
        self.assertFalse(link.is_symlink())
        self.assertEqual(stat.S_IMODE(link.lstat().st_mode), 0o600)
        self.assertEqual(digest, hashlib.sha256(link.read_bytes()).hexdigest())
        self.assertEqual(json.loads(link.read_text()), ITEMS[0])
        self.assertEqual(sorted(p.name for p in review.iterdir()), ["s1.review.jsonl"])

    def test_dangling_symlink_at_the_file(self) -> None:
        review = self.root / "review"
        review.mkdir(mode=0o700)
        target = self.victim.dir / "new.txt"
        (review / "s1.review.jsonl").symlink_to(target)
        self.write(review / "s1.review.jsonl")
        self.assertFalse(target.exists())
        self.victim.untouched(self)

    def test_symlinked_review_directory_is_refused(self) -> None:
        (self.root / "index" / "church").mkdir(parents=True)
        (self.root / "index" / "church" / "review").symlink_to(self.victim.dir)
        with self.assertRaises(RuntimeError):
            self.write(self.root / "index" / "church" / "review" / "victim.txt")
        self.victim.untouched(self)

    def test_symlinked_ancestor_is_refused(self) -> None:
        (self.root / "index").mkdir()
        (self.root / "index" / "church").symlink_to(self.victim.dir)
        for name in ("review/s1.review.jsonl", "victim.txt"):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                self.write(self.root / "index" / "church" / name)
        self.victim.untouched(self)

    def test_ancestor_swapped_for_a_symlink_during_the_write_is_refused(self) -> None:
        """No check-then-use window: swap a component just before it is opened."""
        import preached.privacy as privacy

        (self.root / "index").mkdir()
        (self.root / "index" / "church").mkdir()
        real_open = os.open
        swapped = []

        def racing_open(path, flags, *args, **kwargs):
            if path == "church" and not swapped:
                swapped.append(1)
                (self.root / "index" / "church").rmdir()
                (self.root / "index" / "church").symlink_to(self.victim.dir)
            return real_open(path, flags, *args, **kwargs)

        with patch.object(privacy.os, "open", racing_open), self.assertRaises(RuntimeError):
            self.write(self.root / "index" / "church" / "review" / "s1.review.jsonl")
        self.assertEqual(swapped, [1])
        self.victim.untouched(self)

    def test_relative_path_through_a_symlink_is_refused(self) -> None:
        (self.root / "link").symlink_to(self.victim.dir)
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        with self.assertRaises(RuntimeError):
            self.write(Path("link") / "victim.txt")
        self.victim.untouched(self)

    def test_open_directory_is_tightened_through_its_descriptor(self) -> None:
        review = self.root / "review"
        review.mkdir()
        os.chmod(review, 0o777)
        self.write(review / "s1.review.jsonl")
        self.assertEqual(stat.S_IMODE(review.stat().st_mode), 0o700)

    def test_directory_owned_by_another_user_is_refused(self) -> None:
        review = self.root / "review"
        review.mkdir(mode=0o700)
        with patch("preached.privacy.os.geteuid", return_value=os.geteuid() + 1), self.assertRaises(RuntimeError):
            self.write(review / "s1.review.jsonl")
        self.assertEqual(list(review.iterdir()), [])

    def test_repo_paths_are_still_refused(self) -> None:
        with self.assertRaises(RuntimeError):
            self.write(ROOT / "review" / "x.review.jsonl")
        # Also through a symlink that points into the repo.
        (self.root / "into-repo").symlink_to(ROOT)
        with self.assertRaises(RuntimeError):
            self.write(self.root / "into-repo" / "review" / "x.review.jsonl")


class AsrChunksSymlinkTests(unittest.TestCase):
    """align/asr_chunks.py writes its review file through the same helper."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.victim = Victim(self.root)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PREACHED_PRIVACY")}
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.transcript = self.root / "church-1.json"
        spoken = "Gerald Fenwick brought soup. " + FILLER * 20
        self.transcript.write_text(json.dumps({
            "meta": {"id": "church-1", "title": "Sunday morning"},
            "segments": [{"words": [[w.start, w.end, w.text] for w in words_for(spoken)]}],
        }))
        self.toml = self.root / "privacy.toml"
        self.toml.write_text("# none\n")
        self.index_dir = self.root / "index"
        self.index_dir.mkdir()

    def run_asr(self) -> None:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            asr_chunks.main([str(self.transcript), "--out", str(self.root / "c.jsonl"), "--library", "church",
                             "--privacy", str(self.toml), "--index", str(self.index_dir / "church.sqlite"), *stub_audio(self.transcript)],
                            embedder=embedder, coverage=lambda *_a, **_k: [])

    def test_symlink_at_the_review_file(self) -> None:
        review = self.index_dir / "church" / "review"
        review.mkdir(parents=True, mode=0o700)
        (review / "church-1.review.jsonl").symlink_to(self.victim.file)
        self.run_asr()
        self.victim.untouched(self)
        written = review / "church-1.review.jsonl"
        self.assertFalse(written.is_symlink())
        self.assertIn("Gerald", written.read_text())  # the private file holds the name; the victim does not

    def test_symlinked_review_directory(self) -> None:
        (self.index_dir / "church").mkdir()
        (self.index_dir / "church" / "review").symlink_to(self.victim.dir)
        with self.assertRaises((RuntimeError, SystemExit)):
            self.run_asr()
        self.victim.untouched(self)


class MkdirRaceTests(unittest.TestCase):
    """Round 6: a lost mkdir race (EEXIST) retries the open once; a non-directory still fails closed."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.victim = Victim(self.root)

    def race(self, plant) -> object:
        """Run _open_private_dir on a missing folder; ``plant`` runs just before mkdir, as a rival would."""
        real_mkdir = os.mkdir
        target = self.root / "race"

        def mkdir(path, mode=0o777, *, dir_fd=None):
            if path == "race":
                plant(target)
            return real_mkdir(path, mode, dir_fd=dir_fd)

        with patch("preached.privacy.os.mkdir", mkdir):
            fd = _open_private_dir(target)
        return fd

    def test_create_false_never_makes_a_missing_directory(self) -> None:
        target = self.root / "absent" / "deeper"
        with self.assertRaises(FileNotFoundError):
            _open_private_dir(target, create=False)
        self.assertFalse((self.root / "absent").exists())
        with self.assertRaises(FileNotFoundError):
            read_private_file(target / "x.review.jsonl")
        self.assertFalse((self.root / "absent").exists())

    def test_rival_creates_the_directory_first(self) -> None:
        fd = self.race(lambda target: target.mkdir(mode=0o700))
        self.addCleanup(os.close, fd)
        self.assertTrue(stat.S_ISDIR(os.fstat(fd).st_mode))

    def test_rival_plants_a_symlink_fails_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            self.race(lambda target: target.symlink_to(self.victim.dir))
        self.victim.untouched(self)

    def test_rival_plants_a_file_fails_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            self.race(lambda target: target.write_text("x"))

    def test_eexist_retries_the_open_exactly_once(self) -> None:
        for plant in (lambda target: target.mkdir(mode=0o700), lambda target: target.write_text("x")):
            opens = []
            real_open = os.open

            def counting(path, flags, *args, **kwargs):
                if path == "race":
                    opens.append(path)
                return real_open(path, flags, *args, **kwargs)

            with patch("preached.privacy.os.open", counting):
                try:
                    fd = self.race(plant)
                except RuntimeError:
                    pass
                else:
                    os.close(fd)
            # the first open (missing), then one retry after EEXIST; never a third
            self.assertEqual(len(opens), 2, opens)
            shutil.rmtree(self.root / "race", ignore_errors=True)
            (self.root / "race").unlink(missing_ok=True)

    def test_directory_removed_between_eexist_and_retry_fails_closed_without_looping(self) -> None:
        real_mkdir, real_open = os.mkdir, os.open
        mkdirs = []

        def mkdir(path, mode=0o777, *, dir_fd=None):
            if path == "race":
                mkdirs.append(path)
                # a retry loop would come back here forever; bounded code stops at once
                if len(mkdirs) > 3:
                    raise AssertionError("mkdir retried more than a bounded number of times")
                if len(mkdirs) == 1:
                    (self.root / "race").mkdir(mode=0o700)  # the rival wins the race
            return real_mkdir(path, mode, dir_fd=dir_fd)

        def opener(path, flags, *args, **kwargs):
            if path == "race" and mkdirs and (self.root / "race").exists():
                (self.root / "race").rmdir()  # the rival removes it before the retry
            return real_open(path, flags, *args, **kwargs)

        with patch("preached.privacy.os.mkdir", mkdir), patch("preached.privacy.os.open", opener):
            with self.assertRaises(RuntimeError):
                _open_private_dir(self.root / "race")
        self.assertEqual(len(mkdirs), 1)

    def test_intermediate_component_swapped_fails_closed(self) -> None:
        for create in (True, False):
            with self.subTest(create=create):
                base = self.root / f"swap{create}"
                (base / "mid" / "leaf").mkdir(parents=True, mode=0o700)
                real_open = os.open
                swapped = []

                def swapping(path, flags, *args, **kwargs):
                    if path == "mid" and not swapped:
                        swapped.append(path)
                        (base / "mid" / "leaf").rmdir()
                        (base / "mid").rmdir()
                        (base / "mid").symlink_to(self.victim.dir)
                    return real_open(path, flags, *args, **kwargs)

                with patch("preached.privacy.os.open", swapping):
                    with self.assertRaises(RuntimeError):
                        _open_private_dir(base / "mid" / "leaf", create=create)
                self.assertTrue(swapped)
                self.victim.untouched(self)


if __name__ == "__main__":
    unittest.main()
