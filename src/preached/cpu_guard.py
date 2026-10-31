"""Keep CTranslate2's int8 path off MKL's AMX kernels.

On a Xeon with AMX (the CTO's VM), CTranslate2's int8 CPU path runs through
MKL's AMX kernels and returned corrupted, non-deterministic encoder output:
the same input six times differed by 10-31, with garbage tokens and 15-30 s
holes that moved from run to run (turbo and ``tiny.en``, even on one thread).
With ``MKL_ENABLE_INSTRUCTIONS=AVX512`` (or ``AVX2``) the output was
bit-stable and complete. A desktop CPU without AMX (i9-12900K) is not
affected.

``avoid_amx()`` runs in every transcribe entrypoint before ctranslate2 is
imported: if ``/proc/cpuinfo`` lists ``amx_int8`` or ``amx_tile`` and
``MKL_ENABLE_INSTRUCTIONS`` is unset (or empty), it sets it to ``AVX512``.
MKL reads the variable when it loads, so if ctranslate2 is already imported
it is too late and the call raises instead. An operator's value is kept only
if it is one of ``SAFE_VALUES``, exactly as written; anything else raises.
MKL ignores a value it does not recognise and keeps AMX on: its verbose
output on the CTO's AMX box showed ``AVX512_E4``, ``AVX512_E5``, lowercase
``avx512`` and a typo all still running the AMX kernels. The coverage gate
(``preached.youtube.coverage``) still checks every transcript, since other
faults can corrupt ASR the same way.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import MutableMapping

CPUINFO = Path("/proc/cpuinfo")
AMX_FLAGS = frozenset({"amx_int8", "amx_tile"})
MKL_VAR = "MKL_ENABLE_INSTRUCTIONS"
SAFE_ISA = "AVX512"
# The MKL_ENABLE_INSTRUCTIONS values that stop below AMX, case-sensitive.
# AVX512_E4 (and up) enables AMX; MKL treats an unknown value as unset.
SAFE_VALUES = frozenset({"AVX512", "AVX512_E1", "AVX512_E2", "AVX512_E3", "AVX2", "AVX", "SSE4_2"})


class AmxUnsafe(RuntimeError):
    """AMX could not be ruled out: ctranslate2 was loaded first, or MKL_ENABLE_INSTRUCTIONS is not a safe value."""


def has_amx(cpuinfo: Path = CPUINFO) -> bool:
    """True when any ``flags`` line of ``cpuinfo`` lists an AMX flag. An unreadable file counts as no AMX."""
    try:
        text = cpuinfo.read_text(errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "flags" and AMX_FLAGS & set(value.split()):
            return True
    return False


def avoid_amx(
    *,
    cpuinfo: Path = CPUINFO,
    environ: MutableMapping[str, str] | None = None,
    modules: dict | None = None,
) -> bool:
    """Set ``MKL_ENABLE_INSTRUCTIONS=AVX512`` on an AMX CPU; return True when it was set here.

    Raises ``AmxUnsafe`` when it would have to be set but ctranslate2 is
    already imported, or when it is set to anything but one of ``SAFE_VALUES``.
    """
    environ = os.environ if environ is None else environ
    modules = sys.modules if modules is None else modules
    if not has_amx(cpuinfo):
        return False
    current = environ.get(MKL_VAR)
    if current in SAFE_VALUES:
        return False
    if current:
        raise AmxUnsafe(
            f"this CPU has AMX and {MKL_VAR}={current!r} does not turn it off (MKL ignores values it does not "
            f"recognise, and AVX512_E4 and up allow AMX). Use one of: {', '.join(sorted(SAFE_VALUES))}"
        )
    if "ctranslate2" in modules:
        raise AmxUnsafe(
            f"this CPU has AMX and ctranslate2 is already loaded without {MKL_VAR}; its int8 output can be "
            f"corrupted on AMX. Run with {MKL_VAR}={SAFE_ISA} set in the environment"
        )
    environ[MKL_VAR] = SAFE_ISA
    print(f"cpu has AMX: set {MKL_VAR}={SAFE_ISA} before loading ctranslate2", file=sys.stderr, flush=True)
    return True
