"""Stopping app/server.py: SIGTERM while serving, under load, and before serving.

The loaded tests start the real script, keep 16 clients searching, send
SIGTERM, and require exit 0 with the private bytecode directory removed.
Before the drain (PR #36 r1) bm25 segfaulted (sqlite closed under a handler)
and hybrid aborted in ONNX Runtime on most runs.

Runs per mode: PREACHED_SHUTDOWN_RUNS (default 3). bm25 uses the real Wesley
index when /cache has it, else a generated one. hybrid needs the real index
and the pinned ONNX model; it is skipped without them.
"""

from __future__ import annotations

import http.client
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from preached.store import connect  # noqa: E402

SERVER = ROOT / "app" / "server.py"
PYTHON = ROOT / ".venv" / "bin" / "python"
REAL_INDEX = Path("/cache/index/wesley.sqlite")
ONNX_DIR = Path(os.environ.get("PREACHED_ONNX_DIR", "/cache/models/granite-english-r2-onnx"))
RUNS = int(os.environ.get("PREACHED_SHUTDOWN_RUNS", "3"))
CLIENTS = 16
WORDS = "grace faith love sin holy spirit law gospel heart repentance mercy prayer".split()


def _python() -> str:
    return str(PYTHON) if PYTHON.exists() else sys.executable


def _fixture_index(path: Path, rows: int = 400) -> Path:
    connection = connect(path)
    for n in range(rows):
        text = " ".join(WORDS[(n + i) % len(WORDS)] for i in range(60))
        connection.execute(
            "INSERT INTO chunks (chunk_id, sermon_id, sermon_title, text, sermon_number, word_count) VALUES (?, ?, ?, ?, ?, ?)",
            (f"wesley-{n // 10 + 1:03d}-c{n % 10:04d}", f"wesley-{n // 10 + 1:03d}", "Sermon", text, n // 10 + 1, 60),
        )
    connection.commit()
    connection.close()
    return path


def _env(tmp: str) -> dict:
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", tmp),
        "TMPDIR": tmp,
        "PREACHED_RATE_LIMIT": "1000000",
        "PREACHED_MAX_CONNECTIONS": "64",
        "PREACHED_MAX_CLIENT_CONNECTIONS": "64",
        # PR #29's in-flight cap per client (ignored before it lands): all 16
        # clients share 127.0.0.1 and must be searching, not refused.
        "PREACHED_MAX_CLIENT_REQUESTS": "64",
        **({"PREACHED_ONNX_DIR": os.environ["PREACHED_ONNX_DIR"]} if "PREACHED_ONNX_DIR" in os.environ else {}),
    }


class _Server:
    """app/server.py as a script; ``port`` once it prints PREACHED_LISTENING."""

    def __init__(self, tmp: str, args: list[str], setup: str = "") -> None:
        """``setup`` runs first, in the same interpreter, and the script then runs as __main__ (runpy)."""
        if setup:
            code = (
                "import os, runpy, sys, time\n"
                f"sys.argv = ['server.py', '--port', '0', *{args!r}]\n"
                + setup
                + f"runpy.run_path({str(SERVER)!r}, run_name='__main__')\n"
            )
            command = [_python(), "-c", code]
            env = {**_env(tmp), "PYTHONPATH": f"{ROOT}{os.pathsep}{ROOT / 'src'}"}
        else:
            command = [_python(), str(SERVER), "--port", "0", *args]
            env = _env(tmp)
        self.proc = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.port = None
        for line in self.proc.stdout:
            if line.startswith("PREACHED_LISTENING"):
                self.port = int(line.rsplit(":", 1)[1])
                break
        # Keep reading so a full pipe never blocks the server.
        self._out = threading.Thread(target=self.proc.stdout.read, daemon=True)
        self._out.start()
        self._err: list[str] = []
        self._errt = threading.Thread(target=lambda: self._err.append(self.proc.stderr.read()), daemon=True)
        self._errt.start()

    def stop(self, timeout: float = 60, sig: int = signal.SIGTERM) -> tuple[object, str]:
        self.proc.send_signal(sig)
        try:
            rc = self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            rc = "hang"
        self._errt.join(10)
        self._out.join(10)
        self.proc.stdout.close()
        self.proc.stderr.close()
        return rc, "".join(self._err)


def _hammer(port: int, mode: str, stop: threading.Event, ok: list, n: int) -> None:
    while not stop.is_set():
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", f"/api/search?q={WORDS[n % len(WORDS)]}+{WORDS[(n + 3) % len(WORDS)]}&mode={mode}&k=25")
            response = conn.getresponse()
            response.read()
            if response.status == 200:
                ok.append(1)
            conn.close()
        except (OSError, http.client.HTTPException):
            pass


class LoadedSigtermTests(unittest.TestCase):
    def _loaded_runs(self, mode: str, index: Path, extra: list[str]) -> None:
        failures = []
        served = 0
        for run in range(RUNS):
            with tempfile.TemporaryDirectory() as tmp:
                server = _Server(tmp, ["--index", str(index), *extra])
                self.assertIsNotNone(server.port, "server did not start")
                stop, ok = threading.Event(), []
                clients = [
                    threading.Thread(target=_hammer, args=(server.port, mode, stop, ok, n), daemon=True)
                    for n in range(CLIENTS)
                ]
                for client in clients:
                    client.start()
                deadline = time.monotonic() + 30
                while len(ok) < CLIENTS and time.monotonic() < deadline:
                    time.sleep(0.02)
                rc, err = server.stop()
                stop.set()
                for client in clients:
                    client.join(15)
                leaked = list(Path(tmp).glob("preached-pycache-*"))
                served += len(ok)
                if rc != 0 or leaked or "Traceback" in err or len(ok) < CLIENTS:
                    failures.append((run, rc, len(ok), [p.name for p in leaked], err[-800:]))
        self.assertEqual(failures, [], f"{mode}: {len(failures)}/{RUNS} runs failed")
        self.assertGreater(served, 0)

    def test_sigterm_under_bm25_load_exits_zero_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = REAL_INDEX if REAL_INDEX.is_file() else _fixture_index(Path(tmp) / "wesley.sqlite")
            self._loaded_runs("bm25", index, ["--bm25-only"])

    @unittest.skipUnless(REAL_INDEX.is_file() and (ONNX_DIR).is_dir(), "needs /cache/index/wesley.sqlite and the pinned ONNX model")
    def test_sigterm_under_hybrid_load_exits_zero_and_cleans_up(self) -> None:
        self._loaded_runs("hybrid", REAL_INDEX, [])


class ServingSigtermTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.index = _fixture_index(Path(self.tmp) / "wesley.sqlite", rows=20)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_sigterm_while_serving_idle_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = _Server(tmp, ["--index", str(self.index), "--bm25-only"])
            self.assertIsNotNone(server.port)
            rc, err = server.stop()
            self.assertEqual(rc, 0, err[-2000:])
            self.assertIn("stopping", err)
            self.assertNotIn("Traceback", err)
            self.assertEqual(list(Path(tmp).glob("preached-pycache-*")), [])

    def test_idle_keep_alive_connection_does_not_hold_the_stop(self) -> None:
        # Without the wake-up the handler would sit in its header read for
        # the full 15 s deadline.
        with tempfile.TemporaryDirectory() as tmp:
            server = _Server(tmp, ["--index", str(self.index), "--bm25-only"])
            conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
            conn.request("GET", "/api/search?q=grace&mode=bm25")
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 200)
            idle = socket.create_connection(("127.0.0.1", server.port))  # never sends
            time.sleep(0.2)
            started = time.monotonic()
            rc, err = server.stop()
            self.assertLess(time.monotonic() - started, 5, err[-2000:])
            self.assertEqual(rc, 0, err[-2000:])
            self.assertEqual(list(Path(tmp).glob("preached-pycache-*")), [])
            conn.close()
            idle.close()


# Holds every search for HOLD_S after it starts: touches $MARK, sleeps, then searches.
HOLD = (
    "import preached.abstain as _abs\n"
    "_real = _abs.search_with_confidence\n"
    "def _held(*a, **k):\n"
    "    open(os.environ['MARK'], 'w').close()\n"
    "    time.sleep(HOLD_S)\n"
    "    return _real(*a, **k)\n"
    "_abs.search_with_confidence = _held\n"
)


def _held_search(tmp: str, index: Path, hold_s: float):
    """A bm25 server whose searches take ``hold_s``; the first request is in flight when this returns."""
    mark = Path(tmp) / "in-flight"
    server = _Server(tmp, ["--index", str(index), "--bm25-only"], setup=f"HOLD_S = {hold_s}\nos.environ['MARK'] = {str(mark)!r}\n" + HOLD)
    result: dict = {}

    def request() -> None:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=40)
            conn.request("GET", "/api/search?q=grace&mode=bm25")
            response = conn.getresponse()
            response.read()
            result["status"] = response.status
            conn.close()
        except (OSError, http.client.HTTPException) as exc:
            result["error"] = repr(exc)

    client = threading.Thread(target=request, daemon=True)
    client.start()
    deadline = time.monotonic() + 20
    while not mark.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert mark.exists(), "the search never started"
    return server, client, result


class InFlightTests(unittest.TestCase):
    """Deterministic: a search is held open across the stop, on any machine."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.index = _fixture_index(Path(self.tmp) / "wesley.sqlite", rows=20)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_search_in_flight_at_sigterm_finishes_before_the_index_closes(self) -> None:
        server, client, result = _held_search(self.tmp, self.index, 1.5)
        rc, err = server.stop()
        client.join(15)
        self.assertEqual(result, {"status": 200}, err[-2000:])
        self.assertEqual(rc, 0, err[-2000:])
        # The search was still in flight when the stop began: its 200 is logged after "stopping".
        self.assertIn("stopping", err)
        self.assertIn("GET /api/search 200", err)
        self.assertLess(err.index("stopping"), err.index("GET /api/search 200"), err[-2000:])
        self.assertNotIn("Traceback", err)
        self.assertEqual(list(Path(self.tmp).glob("preached-pycache-*")), [])

    def test_ctrl_c_while_serving_exits_zero(self) -> None:
        server = _Server(self.tmp, ["--index", str(self.index), "--bm25-only"])
        self.assertIsNotNone(server.port)
        rc, err = server.stop(sig=signal.SIGINT)
        self.assertEqual(rc, 0, err[-2000:])
        self.assertIn("stopping", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(list(Path(self.tmp).glob("preached-pycache-*")), [])

    def test_stuck_handler_exits_one_leaves_the_index_open_and_ignores_a_second_ctrl_c(self) -> None:
        # Held past DRAIN_TIMEOUT_S (10 s). The process then waits for that thread and exits 1.
        server, client, _result = _held_search(self.tmp, self.index, 13)
        server.proc.send_signal(signal.SIGTERM)
        time.sleep(1)
        server.proc.send_signal(signal.SIGINT)  # a second stop request does not force an exit
        try:
            rc = server.proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            server.proc.kill()
            server.proc.wait()
            rc = "hang"
        server._errt.join(10)
        server._out.join(10)
        server.proc.stdout.close()
        server.proc.stderr.close()
        err = "".join(server._err)
        client.join(15)
        self.assertEqual(rc, 1, err[-2000:])
        self.assertIn("still running", err)
        self.assertIn("index left open", err)
        # The held search woke to an open index and completed (its socket was shut at half the bound).
        self.assertIn("GET /api/search 200", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(list(Path(self.tmp).glob("preached-pycache-*")), [])


class DrainingGateTests(unittest.TestCase):
    def test_a_connection_accepted_after_drain_began_is_not_served(self) -> None:
        sys.path.insert(0, str(ROOT))
        from app.server import PreachedServer

        served: list = []

        class Recording:
            def __init__(self, request, client_address, server) -> None:
                served.append(request)

        server = PreachedServer(("127.0.0.1", 0), Recording)
        try:
            server.finish_request("before", ("127.0.0.1", 1))
            self.assertEqual(served, ["before"])  # the control: served until drain begins
            self.assertEqual(server.drain(timeout_s=1), [])
            server.finish_request("after", ("127.0.0.1", 2))
            self.assertEqual(served, ["before"])
        finally:
            server.server_close()


class _ScriptRun:
    @staticmethod
    def run(setup: str, argv: list[str], *, tail: str = "") -> tuple[subprocess.CompletedProcess, list[Path]]:
        """app/server.py as __main__ (runpy) after ``setup``; (process, leaked dirs)."""
        code = (
            "import os, runpy, signal, sys, time\n"
            f"sys.argv = ['server.py', *{argv!r}]\n"
            + setup
            + f"runpy.run_path({str(SERVER)!r}, run_name='__main__')\n"
            + tail
        )
        with tempfile.TemporaryDirectory() as tmp:
            env = {**_env(tmp), "PYTHONPATH": f"{ROOT}{os.pathsep}{ROOT / 'src'}"}
            proc = subprocess.run([_python(), "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
            return proc, list(Path(tmp).glob("preached-pycache-*"))


class BeforeServingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.index = _fixture_index(Path(self._tmp.name) / "wesley.sqlite", rows=20)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_sigterm_swallowed_by_an_import_still_stops_before_serving(self) -> None:
        # onnxruntime's native import turns the handler's SystemExit into
        # ImportError; load_search then falls back to BM25. The recorded
        # request must still stop the server before it listens.
        setup = (
            "import preached.backends, preached.search\n"
            "_init = preached.search.Searcher.__init__\n"
            "def _bm25_init(self, connection, model=None, **kw):\n"
            "    _init(self, connection, **kw)\n"
            "preached.search.Searcher.__init__ = _bm25_init\n"
            "def _load(*a, **k):\n"
            "    try:\n"
            "        os.kill(os.getpid(), signal.SIGTERM)\n"
            "        time.sleep(5)\n"
            "    except BaseException as exc:\n"
            "        raise ImportError('onnxruntime import interrupted') from exc\n"
            "preached.backends.load_embedder = _load\n"
        )
        proc, leaked = _ScriptRun.run(setup, ["--port", "0", "--index", str(self.index)])
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("embedding model unavailable", proc.stderr)  # the swallow happened
        self.assertNotIn("PREACHED_LISTENING", proc.stdout)
        self.assertEqual(leaked, [])

    def test_nonzero_exit_while_serving_is_kept(self) -> None:
        setup = "import socketserver\nsocketserver.BaseServer.serve_forever = lambda self, *a, **k: sys.exit(3)\n"
        proc, leaked = _ScriptRun.run(setup, ["--port", "0", "--index", str(self.index), "--bm25-only"])
        self.assertEqual(proc.returncode, 3, proc.stderr[-2000:])
        self.assertIn("stopping", proc.stderr)
        self.assertEqual(leaked, [])

    def test_failed_mkdtemp_leaves_sigterm_unblocked(self) -> None:
        setup = "import tempfile\ndef _fail(*a, **k):\n    raise OSError('no space')\ntempfile.mkdtemp = _fail\ntry:\n    "
        tail = "except OSError:\n    print('blocked' if signal.SIGTERM in signal.pthread_sigmask(signal.SIG_BLOCK, []) else 'unblocked')\n"
        proc, _ = _ScriptRun.run(setup, ["--index", "/nonexistent/x.sqlite"], tail=tail)
        self.assertEqual(proc.stdout.strip(), "unblocked", proc.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
