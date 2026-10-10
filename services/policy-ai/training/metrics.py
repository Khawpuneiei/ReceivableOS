"""Test metrics for the credit model (brief section 8.5): AUC, PR-AUC, Brier, ECE (equal-width bins), KS."""

from __future__ import annotations

import numpy as np


def _ranks(x: np.ndarray) -> np.ndarray:
    """Average ranks (1-based), ties share their mean rank."""
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=float)
    sorted_x = x[order]
    starts = np.r_[0, np.flatnonzero(np.diff(sorted_x)) + 1]
    ends = np.r_[starts[1:], len(x)]
    for s, e in zip(starts, ends, strict=True):
        ranks[order[s:e]] = (s + e + 1) / 2
    return ranks


def auc(y: np.ndarray, p: np.ndarray) -> float:
    y, p = np.asarray(y, dtype=int), np.asarray(p, dtype=float)
    n_pos, n_neg = y.sum(), len(y) - y.sum()
    return float((_ranks(p)[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def pr_auc(y: np.ndarray, p: np.ndarray) -> float:
    """Average precision: mean precision at each positive, ranking by descending score."""
    y, p = np.asarray(y, dtype=int), np.asarray(p, dtype=float)
    order = np.argsort(-p, kind="mergesort")
    hits = y[order]
    precision = np.cumsum(hits) / np.arange(1, len(hits) + 1)
    return float((precision * hits).sum() / hits.sum())


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2))


def reliability(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    """Per equal-width bin: count, mean predicted, observed rate (empty bins left out)."""
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    idx = np.minimum((p * bins).astype(int), bins - 1)
    out = []
    for b in range(bins):
        mask = idx == b
        if mask.any():
            out.append(
                {
                    "bin": b,
                    "n": int(mask.sum()),
                    "mean_pd": float(p[mask].mean()),
                    "rate": float(y[mask].mean()),
                }
            )
    return out


def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error: bin-weighted |mean predicted - observed rate|."""
    n = len(y)
    return float(sum(r["n"] / n * abs(r["mean_pd"] - r["rate"]) for r in reliability(y, p, bins)))


def ks(y: np.ndarray, p: np.ndarray) -> float:
    """Kolmogorov-Smirnov: largest gap between the score CDFs of defaults and non-defaults."""
    y, p = np.asarray(y, dtype=int), np.asarray(p, dtype=float)
    grid = np.unique(p)
    cdf_pos = np.searchsorted(np.sort(p[y == 1]), grid, side="right") / max(y.sum(), 1)
    cdf_neg = np.searchsorted(np.sort(p[y == 0]), grid, side="right") / max((1 - y).sum(), 1)
    return float(np.max(np.abs(cdf_pos - cdf_neg)))


def report(y: np.ndarray, p: np.ndarray, bins: int = 10) -> dict:
    return {
        "rows": int(len(y)),
        "base_rate": round(float(np.mean(y)), 6),
        "auc": round(auc(y, p), 4),
        "pr_auc": round(pr_auc(y, p), 4),
        "brier": round(brier(y, p), 6),
        "ece": round(ece(y, p, bins), 6),
        "ks": round(ks(y, p), 4),
    }
