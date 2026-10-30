"""Bootstrap confidence intervals over questions. numpy only.

With ~35 answerable questions one question moves a mean by ~0.03, so every
headline number gets a 95% interval, and model-vs-model claims use a paired
bootstrap (the same resampled questions for both systems).
"""

from __future__ import annotations

import numpy as np

RESAMPLES = 10_000
SEED = 20261030


def _indices(n: int, resamples: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, n, size=(resamples, n))


def bootstrap_ci(values: list[float], resamples: int = RESAMPLES, seed: int = SEED) -> dict:
    x = np.asarray(values, dtype=np.float64)
    means = x[_indices(len(x), resamples, seed)].mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return {"mean": float(x.mean()), "ci95": [float(low), float(high)]}


def paired_bootstrap(a: list[float], b: list[float], resamples: int = RESAMPLES, seed: int = SEED) -> dict:
    """Mean of a - b with a 95% interval, and the share of resamples where a <= b.

    p_le_zero near 0 means a is reliably better; near 1, reliably worse.
    """
    x = np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)
    means = x[_indices(len(x), resamples, seed)].mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])
    return {
        "diff": float(x.mean()),
        "ci95": [float(low), float(high)],
        "p_le_zero": float((means <= 0).mean()),
        "wins": int((x > 0).sum()),
        "ties": int((x == 0).sum()),
        "losses": int((x < 0).sum()),
    }
