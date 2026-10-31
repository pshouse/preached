"""AMX guard: MKL's AMX int8 kernels corrupted CTranslate2 output on the CTO's Xeon."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from preached.cpu_guard import MKL_VAR, AmxUnsafe, avoid_amx, has_amx

XEON = """processor\t: 0
vendor_id\t: GenuineIntel
model name\t: Intel(R) Xeon(R) Platinum 8480+
flags\t\t: fpu vme sse sse2 avx avx2 avx512f avx512_vnni amx_bf16 avx512_fp16 amx_tile amx_int8
"""
TILE_ONLY = "flags\t\t: fpu sse avx2 amx_tile\n"
DESKTOP = """processor\t: 0
model name\t: 12th Gen Intel(R) Core(TM) i9-12900K
flags\t\t: fpu vme sse sse2 avx avx2 fma avx_vnni
bugs\t\t: amx_int8_is_not_a_flag_here
"""


class GuardTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def cpuinfo(self, text: str) -> Path:
        path = self.dir / "cpuinfo"
        path.write_text(text)
        return path

    def test_detects_amx_from_the_flags_line_only(self) -> None:
        self.assertTrue(has_amx(self.cpuinfo(XEON)))
        self.assertTrue(has_amx(self.cpuinfo(TILE_ONLY)))
        self.assertFalse(has_amx(self.cpuinfo(DESKTOP)))
        self.assertFalse(has_amx(self.dir / "missing"))

    def test_sets_avx512_on_an_amx_cpu(self) -> None:
        env: dict[str, str] = {}
        self.assertTrue(avoid_amx(cpuinfo=self.cpuinfo(XEON), environ=env, modules={}))
        self.assertEqual(env, {MKL_VAR: "AVX512"})

    def test_leaves_a_desktop_cpu_and_an_operator_value_alone(self) -> None:
        env: dict[str, str] = {}
        self.assertFalse(avoid_amx(cpuinfo=self.cpuinfo(DESKTOP), environ=env, modules={"ctranslate2": object()}))
        self.assertEqual(env, {})
        env = {MKL_VAR: "AVX2"}
        self.assertFalse(avoid_amx(cpuinfo=self.cpuinfo(XEON), environ=env, modules={"ctranslate2": object()}))
        self.assertEqual(env, {MKL_VAR: "AVX2"})

    def test_refuses_when_ctranslate2_is_already_loaded(self) -> None:
        env: dict[str, str] = {}
        with self.assertRaises(AmxUnsafe) as caught:
            avoid_amx(cpuinfo=self.cpuinfo(XEON), environ=env, modules={"ctranslate2": object()})
        self.assertIn(MKL_VAR, str(caught.exception))
        self.assertEqual(env, {})

    def test_transcribe_entrypoint_runs_the_guard_before_loading_the_model(self) -> None:
        from unittest.mock import patch

        from preached.youtube import transcribe

        calls: list[str] = []
        with patch.object(transcribe, "avoid_amx", side_effect=lambda: calls.append("guard")), \
                patch.dict("sys.modules", {"faster_whisper": None}):
            with self.assertRaises(RuntimeError):  # faster_whisper import blocked after the guard
                transcribe._run(Path("x.wav"), device="cpu", compute_type="int8", model_name="tiny.en")
        self.assertEqual(calls, ["guard"])

    def test_ingest_transcriber_runs_the_guard_before_ctranslate2(self) -> None:
        import sys
        from unittest.mock import patch

        root = Path(__file__).resolve().parents[1] / "ingest"
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        import transcribe as ingest_transcribe

        calls: list[str] = []
        with patch.object(ingest_transcribe, "avoid_amx", side_effect=lambda: calls.append("guard")), \
                patch.object(ingest_transcribe, "_preload_cuda_libs", side_effect=lambda: calls.append("cuda")), \
                patch.dict("sys.modules", {"faster_whisper": None}):
            with self.assertRaises(ImportError):
                ingest_transcribe.Transcriber()
        self.assertEqual(calls, ["guard", "cuda"])


if __name__ == "__main__":
    unittest.main()
