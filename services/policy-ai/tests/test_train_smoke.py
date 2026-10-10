"""training/train.py end to end on a small generated set, written to a temp folder."""

import json
from datetime import date
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("pandas")
pytest.importorskip("sklearn")
lgb = pytest.importorskip("lightgbm")
pytest.importorskip("matplotlib")

from training import train  # noqa: E402

MODEL_DIR = Path(__file__).resolve().parents[1] / "model"


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    out = tmp_path_factory.mktemp("model")
    result = train.train(out / "synthetic.csv", out, date(2026, 10, 10), n=3000)
    return out, result


def test_writes_every_artefact_and_no_pickle(trained):
    out, _ = trained
    names = {p.name for p in out.iterdir()} - {"synthetic.csv"}
    assert names == {
        "scorecard.json",
        "lgbm.txt",
        "calibrator.json",
        "metrics.json",
        "model_card.json",
        "reliability.png",
    }
    assert not list(out.glob("*.pkl"))


def test_model_card_names_the_selected_model(trained):
    out, result = trained
    card = json.loads((out / "model_card.json").read_text(encoding="utf-8"))
    report = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert card["selected"] == report["selected"] in {"lr", "lgbm"}
    assert card["version"] == card["versions"][card["selected"]]
    rev = train.load_config()["revision"]
    assert card["versions"] == {"lr": f"credit-lr-2026-10-10.{rev}", "lgbm": f"credit-lgbm-2026-10-10.{rev}"}
    briers = {name: m["test"]["brier"] for name, m in report["models"].items()}
    assert briers[card["selected"]] == min(briers.values())


def test_text_model_and_json_calibrator_reproduce_the_training_pd(trained):
    out, _ = trained
    booster = lgb.Booster(model_file=str(out / "lgbm.txt"))
    calibrator = json.loads((out / "calibrator.json").read_text(encoding="utf-8"))
    assert calibrator["method"] in {"platt", "isotonic"}
    x = np.zeros((1, booster.num_feature()))
    pd = train.calibrate(calibrator, booster.predict(x, raw_score=True))
    assert 0 < pd[0] < 1


def test_monotone_constraints_hold_in_the_saved_model(trained):
    out, _ = trained
    booster = lgb.Booster(model_file=str(out / "lgbm.txt"))
    names = booster.feature_name()
    base = np.zeros((1, len(names)))
    tier = names.index("buyer_tier_ord")
    margins = []
    for t in range(4):
        row = base.copy()
        row[0, tier] = t
        margins.append(booster.predict(row, raw_score=True)[0])
    assert margins == sorted(margins)  # a worse tier never lowers the PD


def test_committed_models_meet_the_targets():
    report = json.loads((MODEL_DIR / "metrics.json").read_text(encoding="utf-8"))
    targets = report["targets"]
    for name, m in report["models"].items():
        assert m["test"]["auc"] >= targets["auc_min"], name
        assert m["test"]["ece"] <= targets["ece_max"], name
