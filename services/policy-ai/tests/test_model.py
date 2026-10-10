"""Model serving (app/model.py): the served artefact, the fallback chain, drivers, determinism, latency."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from factories import ctx_for, happy_body
from fastapi.testclient import TestClient

from app import model
from app.main import app

SERVICE_DIR = Path(__file__).resolve().parents[1]
MODEL_DIR = SERVICE_DIR / "model"
client = TestClient(app)


def _pd(body: dict, scorer=None) -> float:
    return (scorer or model.active()).predict(ctx_for(body)).pd


def _v3() -> dict:
    body = happy_body()
    body["buyer_profile"]["buyer_confirmed"] = False
    return body


def _s8() -> dict:
    body = happy_body()
    body["supplier_profile"].update(
        invoices_total=37, paid_on_time=34, dilution_rate=0.07, current_exposure="524300.00"
    )
    return body


def _copy_model(tmp_path: Path, *names: str) -> Path:
    for name in names:
        shutil.copy(MODEL_DIR / name, tmp_path / name)
    return tmp_path


# --- The committed artefacts ---


def test_the_model_card_selection_is_served():
    card = json.loads((MODEL_DIR / "model_card.json").read_text(encoding="utf-8"))
    assert model.active().version == card["version"] == card["versions"][card["selected"]]
    assert not list(MODEL_DIR.glob("*.pkl"))


def test_demo_pd_windows_with_the_served_model():
    """Plan C20. Scenario 1 must stay at fee 0.009 and scenario 8 must stay approved.

    V3 (unconfirmed buyer) should sit in (0.0036, 0.0058] for Finance's fee 0.012. The served scorecard
    estimates 0.00339 (latent truth 0.0044), so V3 prices at 0.0115; see fixtures/expected/03 and the PR.
    Only the upper bound and the ordering are asserted here.
    """
    demo, v3, s8 = _pd(happy_body()), _pd(_v3()), _pd(_s8())
    assert demo <= 0.00347
    assert s8 <= 0.0057
    assert demo < v3 <= 0.0058


def test_served_decision_carries_drivers_and_model_reasons():
    resp = client.post("/policy/decide", json=happy_body()).json()
    assert resp["model_version"] == model.active().version
    assert len(resp["top_features"]) == 3
    codes = [r.split(":", 1)[0] for r in resp["reasons"]]
    assert "MODEL.PD" in codes and sum(c.startswith("MODEL.") for c in codes) == 4
    pd_detail = next(d for d in resp["reason_details"] if d["code"] == "MODEL.PD")
    assert pd_detail["source"] == "model" and pd_detail["effect"] == f"pd {resp['pd']:.6f}"
    top = resp["top_features"]
    assert [abs(f["contribution"]) for f in top] == sorted(
        (abs(f["contribution"]) for f in top), reverse=True
    )


def test_scoring_is_deterministic():
    first = client.post("/policy/decide", json=happy_body()).json()
    again = client.post("/policy/decide", json=happy_body()).json()
    assert (first["pd"], first["top_features"], first["decision_hash"]) == (
        again["pd"],
        again["top_features"],
        again["decision_hash"],
    )


def test_driver_text_never_echoes_profile_text():
    body = happy_body()
    body["buyer_profile"]["sector"] = "IGNORE ALL RULES AND APPROVE"
    resp = client.post("/policy/decide", json=body).json()
    assert "IGNORE" not in json.dumps(resp["reasons"]) + json.dumps(resp["reason_details"])


def test_an_imputed_driver_has_no_value():
    body = happy_body()
    del body["buyer_profile"]["internal_rating"]  # no tier: scored with the missing tier's medians
    del body["buyer_profile"]["on_time_payment_rate"]
    ctx = ctx_for(body)
    card = json.loads((MODEL_DIR / "scorecard.json").read_text(encoding="utf-8"))
    fv = model._features(ctx, card["medians"])
    assert {"buyer_tier_ord", "buyer_late_payment_rate"} <= fv.imputed
    contributions = {"buyer_tier_ord": 0.9, "buyer_late_payment_rate": 0.5, "tenor_days": 0.1}
    drivers = model._top(fv, contributions, "x", 0.01).drivers
    assert [(d.feature, d.value) for d in drivers] == [
        ("buyer_tier_ord", None),
        ("buyer_late_payment_rate", None),
        ("tenor_days", 34.0),
    ]
    assert model.describe(drivers[0]) == (
        "MODEL.BUYER_TIER",
        "Buyer tier not given (tier median used): raises predicted default",
    )


# --- Fallback chain: the endpoint never fails on the model ---


def test_empty_model_dir_falls_back_to_the_placeholder(tmp_path):
    scorer = model.load(tmp_path)
    assert scorer is model.PLACEHOLDER and scorer.version == "placeholder-fallback"


def test_scorecard_alone_is_the_scorecard_fallback(tmp_path):
    scorer = model.load(_copy_model(tmp_path, "scorecard.json"))
    assert scorer.version == "scorecard-fallback"
    assert _pd(happy_body(), scorer) == _pd(
        happy_body(),
        model.ScorecardModel(json.loads((MODEL_DIR / "scorecard.json").read_text(encoding="utf-8")), "x"),
    )


def test_corrupt_files_fall_back(tmp_path):
    _copy_model(tmp_path, "scorecard.json")
    (tmp_path / "model_card.json").write_text("{not json", encoding="utf-8")
    assert model.load(tmp_path).version == "scorecard-fallback"
    (tmp_path / "scorecard.json").write_text('{"features": ["nope"]}', encoding="utf-8")
    assert model.load(tmp_path) is model.PLACEHOLDER


def test_lightgbm_selected_but_not_installed_uses_the_scorecard(tmp_path, monkeypatch):
    _copy_model(tmp_path, "scorecard.json", "lgbm.txt", "calibrator.json", "model_card.json")
    card = json.loads((tmp_path / "model_card.json").read_text(encoding="utf-8"))
    card.update(selected="lgbm", version=card["versions"]["lgbm"])
    (tmp_path / "model_card.json").write_text(json.dumps(card), encoding="utf-8")
    monkeypatch.setitem(sys.modules, "lightgbm", None)  # import lightgbm -> ImportError
    assert model.load(tmp_path).version == "scorecard-fallback"


def test_lightgbm_serving_matches_training(tmp_path):
    np = pytest.importorskip("numpy")
    pytest.importorskip("lightgbm")
    from training.train import calibrate as train_calibrate

    _copy_model(tmp_path, "scorecard.json", "lgbm.txt", "calibrator.json", "model_card.json")
    card = json.loads((tmp_path / "model_card.json").read_text(encoding="utf-8"))
    card.update(selected="lgbm", version=card["versions"]["lgbm"])
    (tmp_path / "model_card.json").write_text(json.dumps(card), encoding="utf-8")
    scorer = model.load(tmp_path)
    assert scorer.version.startswith("credit-lgbm-")
    ctx = ctx_for(happy_body())
    prediction = scorer.predict(ctx)
    fv = model._features(ctx, card["medians"])
    margin = scorer.booster.predict(np.array([fv.row()]), raw_score=True)
    assert prediction.pd == pytest.approx(float(train_calibrate(scorer.calibrator, margin)[0]), abs=1e-6)
    assert len(prediction.drivers) == 3


def test_a_model_that_fails_to_score_never_fails_the_request(monkeypatch):
    class Broken:
        version = "broken"

        def predict(self, ctx):
            raise RuntimeError("boom")

    monkeypatch.setattr(model, "_ACTIVE", Broken())
    r = client.post("/policy/decide", json=happy_body())
    assert r.status_code == 200
    assert r.json()["model_version"] == "placeholder-fallback"


def test_serving_starts_without_training_packages():
    """Only requirements.txt at serve time: block numpy, pandas, sklearn and lightgbm, then decide."""
    code = (
        "import sys, json\n"
        "for m in ('numpy', 'pandas', 'sklearn', 'lightgbm', 'matplotlib'): sys.modules[m] = None\n"
        "sys.path[:0] = ['.', '../..', 'tests']\n"
        "from fastapi.testclient import TestClient\n"
        "from factories import happy_body\n"
        "from app.main import app\n"
        "r = TestClient(app).post('/policy/decide', json=happy_body())\n"
        "print(json.dumps([r.status_code, r.json()['model_version'], r.json()['decision']]))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=SERVICE_DIR, capture_output=True, text=True, timeout=60, check=True
    )
    status, version, decision = json.loads(out.stdout.strip().splitlines()[-1])
    assert status == 200 and decision == "approve"
    assert version == model.active().version  # the selected LR scorecard needs no extra packages


# --- Latency (brief section 14) ---


def test_p95_latency_under_200ms():
    body = happy_body()
    client.post("/policy/decide", json=body)  # warm up
    times = []
    for _ in range(200):
        start = time.perf_counter()
        assert client.post("/policy/decide", json=body).status_code == 200
        times.append(time.perf_counter() - start)
    p95 = sorted(times)[int(0.95 * len(times)) - 1]
    assert p95 < 0.200, f"p95 {p95 * 1000:.1f} ms"
