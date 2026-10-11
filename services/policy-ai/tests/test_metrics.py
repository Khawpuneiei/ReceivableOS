"""training/metrics.py on toy arrays, and the scorecard points scale (app/scorecard.py)."""

import json
import math
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from training import metrics  # noqa: E402

from app import scorecard  # noqa: E402

Y = np.array([0, 0, 1, 1, 0, 1, 0, 0])
P = np.array([0.1, 0.4, 0.35, 0.8, 0.1, 0.9, 0.2, 0.35])
CARD_PATH = Path(__file__).resolve().parents[1] / "model" / "scorecard.json"


def test_auc_counts_ties_as_half():
    # positives 0.35, 0.8, 0.9 vs negatives 0.1, 0.4, 0.1, 0.2, 0.35: 3 + 5 + 5 wins, 0.35 beats 3 and ties 1
    assert metrics.auc(Y, P) == pytest.approx((3.5 + 5 + 5) / 15)


def test_brier_ece_ks_and_pr_auc():
    assert metrics.brier(np.array([0, 1]), np.array([0.2, 0.6])) == pytest.approx((0.04 + 0.16) / 2)
    # two bins: [0.1, 0.1] observed 0 and [0.9, 0.9] observed 1 -> error 0.1 in each
    assert metrics.ece(np.array([0, 0, 1, 1]), np.array([0.1, 0.1, 0.9, 0.9])) == pytest.approx(0.1)
    assert metrics.ks(np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.8, 0.9])) == pytest.approx(1.0)
    assert metrics.pr_auc(np.array([1, 0, 1]), np.array([0.9, 0.8, 0.7])) == pytest.approx((1 + 2 / 3) / 2)


def test_metrics_agree_with_sklearn():
    sk = pytest.importorskip("sklearn.metrics")
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 500)
    p = np.clip(y * 0.3 + rng.random(500) * 0.7, 0, 1)
    assert metrics.auc(y, p) == pytest.approx(sk.roc_auc_score(y, p))
    assert metrics.pr_auc(y, p) == pytest.approx(sk.average_precision_score(y, p))
    assert metrics.brier(y, p) == pytest.approx(sk.brier_score_loss(y, p))


def test_scorecard_points_round_trip():
    card = json.loads(CARD_PATH.read_text(encoding="utf-8"))
    factor, offset = scorecard.scaling(card)
    assert factor == pytest.approx(20 / math.log(2)) and offset == pytest.approx(600 - factor * math.log(50))
    assert scorecard.pd_from_score(card, 600) == pytest.approx(1 / 51)  # 50:1 good:bad odds
    assert scorecard.pd_from_score(card, 620) == pytest.approx(1 / 101)  # PDO 20 doubles the odds
    values = {name: card["means"][name] for name in card["features"]}
    values["buyer_tier_ord"] = 2.0
    assert scorecard.pd_from_score(card, scorecard.score(card, values)) == pytest.approx(
        scorecard.predict_pd(card, values)
    )


def test_scorecard_artefact_is_complete():
    card = json.loads(CARD_PATH.read_text(encoding="utf-8"))
    from app.features import FEATURES, IMPUTABLE

    assert card["features"] == list(FEATURES)
    assert set(card["coefficients"]) == set(card["means"]) == set(card["scales"]) == set(FEATURES)
    assert card["version"].startswith("credit-lr-")
    assert set(card["medians"]["tiers"]) == set("ABCD")
    assert all(set(m) == set(IMPUTABLE) for m in card["medians"]["tiers"].values())
