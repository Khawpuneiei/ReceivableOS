"""Train the credit PD model on the synthetic invoices (services/policy-ai/CLAUDE.md sections 8.4-8.5).

Run from services/policy-ai:  PYTHONPATH=.:../.. python -m training.train [--data CSV] [--out DIR]

Features come from app/features.py, the same function serving uses. Time split by cohort: train 1-16,
validation 17-20, test 21-24 (training/train_config.yaml). Missing values take the train split's tier
medians, which are saved with the model. Baseline: standardised L2 logistic regression, saved as a points
scorecard in model/scorecard.json (plain JSON, no pickle). Main model: LightGBM with monotone constraints,
saved in LightGBM's text format (model/lgbm.txt) with a Platt or isotonic calibrator fitted on the validation
split (model/calibrator.json). The model with the better test Brier is selected in model/model_card.json;
metrics.json and reliability.png report both side by side.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.linear_model import LogisticRegression

from app import scorecard
from app.features import FEATURES, IMPUTABLE, MONOTONE, build_features
from app.profiles import TIERS, normalise_buyer, normalise_supplier
from training import metrics, synth

CONFIG_PATH = Path(__file__).resolve().parent / "train_config.yaml"


def load_config(path: Path = CONFIG_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_rows(data: Path, n: int | None = None) -> pd.DataFrame:
    """The training CSV; generated from the synth config's seed when it doesn't exist yet."""
    if not data.exists():
        synth.write(synth.generate(synth.load_config(), n), data)
    return pd.read_csv(data, keep_default_na=True)


def feature_matrix(rows: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(X with NaN where a profile left a value out, tier index per row) via app.features."""
    xs, tiers = [], []
    for row in rows.to_dict("records"):
        invoice, supplier, buyer, as_of = synth.profiles(row)
        b = normalise_buyer(buyer)
        xs.append(build_features(invoice, normalise_supplier(supplier), b, as_of).row())
        tiers.append(TIERS.index(b.credit_tier))
    return np.array(xs, dtype=float), np.array(tiers)


def tier_medians(x: np.ndarray, tiers: np.ndarray, missing_tier: str) -> dict:
    """Medians of the imputable features per tier, from the rows given (the train split)."""
    cols = [FEATURES.index(name) for name in IMPUTABLE]
    out = {}
    for t, tier in enumerate(TIERS):
        block = x[tiers == t][:, cols]
        out[tier] = {name: round(float(np.nanmedian(block[:, i])), 6) for i, name in enumerate(IMPUTABLE)}
    return {"missing_tier": missing_tier, "tiers": out}


def impute(x: np.ndarray, tiers: np.ndarray, medians: dict) -> np.ndarray:
    x = x.copy()
    for t, tier in enumerate(TIERS):
        for name, value in medians["tiers"][tier].items():
            col = FEATURES.index(name)
            gap = (tiers == t) & np.isnan(x[:, col])
            x[gap, col] = value
    return x


def split_masks(rows: pd.DataFrame, cfg: dict) -> dict[str, np.ndarray]:
    cohort = rows["cohort"].to_numpy()
    return {name: (cohort >= lo) & (cohort <= hi) for name, (lo, hi) in cfg["split"].items()}


def fit_scorecard(x: np.ndarray, y: np.ndarray, cfg: dict, version: str, medians: dict) -> dict:
    """Standardised L2 logistic regression, returned as the scorecard JSON."""
    means = x.mean(axis=0)
    scales = x.std(axis=0)
    scales[scales == 0] = 1.0
    lr_cfg = cfg["logistic_regression"]
    lr = LogisticRegression(C=lr_cfg["C"], max_iter=lr_cfg["max_iter"])
    lr.fit((x - means) / scales, y)
    coef = lr.coef_[0]
    card = {
        "version": version,
        "model": "logistic_regression_l2_standardised",
        "features": list(FEATURES),
        "intercept": float(lr.intercept_[0]),
        "coefficients": {f: float(c) for f, c in zip(FEATURES, coef, strict=True)},
        "means": {f: float(m) for f, m in zip(FEATURES, means, strict=True)},
        "scales": {f: float(s) for f, s in zip(FEATURES, scales, strict=True)},
        "points": dict(cfg["scorecard"]),
        "medians": medians,
    }
    factor, offset = scorecard.scaling(card)
    card["points"]["base_points"] = offset - factor * (
        card["intercept"] - float(np.sum(coef * means / scales))
    )
    card["points"]["per_unit"] = {
        f: float(-factor * c / s) for f, c, s in zip(FEATURES, coef, scales, strict=True)
    }
    return card


def scorecard_pd(card: dict, x: np.ndarray) -> np.ndarray:
    z = card["intercept"] + (
        (x - np.array([card["means"][f] for f in FEATURES])) / np.array([card["scales"][f] for f in FEATURES])
    ) @ np.array([card["coefficients"][f] for f in FEATURES])
    return 1 / (1 + np.exp(-z))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def fit_lightgbm(x: np.ndarray, y: np.ndarray, masks: dict, cfg: dict):
    """LightGBM with monotone constraints, early-stopped on the validation split."""
    import lightgbm as lgb

    lgb_cfg = cfg["lightgbm"]
    params = {**lgb_cfg["params"], "monotone_constraints": [MONOTONE[f] for f in FEATURES]}
    train_set = lgb.Dataset(x[masks["train"]], y[masks["train"]], feature_name=list(FEATURES))
    valid_set = lgb.Dataset(x[masks["validation"]], y[masks["validation"]], reference=train_set)
    booster = lgb.train(
        params,
        train_set,
        num_boost_round=lgb_cfg["max_rounds"],
        valid_sets=[valid_set],
        callbacks=[lgb.early_stopping(lgb_cfg["early_stopping_rounds"], verbose=False)],
    )
    return booster


def fit_calibrators(margin: np.ndarray, y: np.ndarray, cfg: dict) -> dict[str, dict]:
    """Platt (a x margin + b) and isotonic (step function over the margin), both as plain JSON."""
    from sklearn.isotonic import IsotonicRegression

    out = {}
    if "platt" in cfg["calibration"]["methods"]:
        platt = LogisticRegression(C=1e6, max_iter=1000).fit(margin.reshape(-1, 1), y)
        out["platt"] = {"method": "platt", "a": float(platt.coef_[0][0]), "b": float(platt.intercept_[0])}
    if "isotonic" in cfg["calibration"]["methods"]:
        floor = cfg["calibration"]["min_pd"]
        iso = IsotonicRegression(out_of_bounds="clip", y_min=floor, y_max=1 - floor).fit(margin, y)
        out["isotonic"] = {
            "method": "isotonic",
            "x": [float(v) for v in iso.X_thresholds_],
            "y": [float(v) for v in iso.y_thresholds_],
        }
    return out


def calibrate(calibrator: dict, margin: np.ndarray) -> np.ndarray:
    """Same maths as app/model.py, vectorised."""
    if calibrator["method"] == "platt":
        return 1 / (1 + np.exp(-(calibrator["a"] * margin + calibrator["b"])))
    return np.interp(margin, calibrator["x"], calibrator["y"])


def reliability_plot(path: Path, y: np.ndarray, curves: dict[str, np.ndarray], bins: int) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5, 5), dpi=100)
    top = 0.0
    for name, p in curves.items():
        order = np.argsort(p, kind="mergesort")
        chunks = np.array_split(order, bins)  # equal-count bins: most PDs sit near zero
        xs = [float(p[c].mean()) for c in chunks]
        ys = [float(y[c].mean()) for c in chunks]
        ax.plot(xs, ys, marker="o", label=f"{name} ({bins} equal-count bins)")
        top = max(top, *xs, *ys)
    ax.plot([0, top], [0, top], linestyle="--", color="grey", label="perfect calibration")
    ax.set_xlabel("predicted PD (test, cohorts 21-24)")
    ax.set_ylabel("observed default rate")
    ax.set_title("Reliability on the drifted test split")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def select(models: dict[str, dict]) -> str:
    """Serve the better test Brier; AUC breaks a tie (brief 8.4)."""
    return min(models, key=lambda name: (models[name]["test"]["brier"], -models[name]["test"]["auc"]))


def train(data: Path, out: Path, version_date: date, cfg: dict | None = None, n: int | None = None) -> dict:
    cfg = cfg or load_config()
    rows = load_rows(data, n)
    x_raw, tiers = feature_matrix(rows)
    y = rows["y"].to_numpy().astype(int)
    masks = split_masks(rows, cfg)
    medians = tier_medians(x_raw[masks["train"]], tiers[masks["train"]], cfg["missing_tier"])
    x = impute(x_raw, tiers, medians)
    bins = cfg["ece_bins"]

    def report(p: np.ndarray) -> dict:
        return {part: metrics.report(y[masks[part]], p[masks[part]], bins) for part in ("validation", "test")}

    card = fit_scorecard(x[masks["train"]], y[masks["train"]], cfg, f"credit-lr-{version_date}.1", medians)
    lr_pd = scorecard_pd(card, x)

    booster = fit_lightgbm(x, y, masks, cfg)
    margin = booster.predict(x, raw_score=True)
    calibrators = fit_calibrators(margin[masks["validation"]], y[masks["validation"]], cfg)
    val_brier = {
        name: metrics.brier(y[masks["validation"]], calibrate(c, margin[masks["validation"]]))
        for name, c in calibrators.items()
    }
    calibrator = calibrators[min(val_brier, key=val_brier.get)]
    calibrator["validation_brier"] = {k: round(v, 6) for k, v in val_brier.items()}
    lgbm_pd = calibrate(calibrator, margin)

    models = {"lr": report(lr_pd), "lgbm": report(lgbm_pd)}
    selected = select(models)
    versions = {"lr": card["version"], "lgbm": f"credit-lgbm-{version_date}.1"}
    synth_cfg = synth.load_config()
    provenance = {
        "data": str(data.name),
        "data_sha256": _sha256(data),
        "synth_config_sha256": synth.config_sha256(),
        "train_config_sha256": _sha256(CONFIG_PATH),
        "seed": synth_cfg["seed"],
        "rows": {part: int(mask.sum()) for part, mask in masks.items()},
        "base_rate": round(float(y.mean()), 6),
    }
    card["training"] = provenance
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "scorecard.json", card)
    booster.save_model(str(out / "lgbm.txt"), num_iteration=booster.best_iteration)
    _write_json(out / "calibrator.json", calibrator)
    reliability_plot(
        out / "reliability.png",
        y[masks["test"]],
        {n: p[masks["test"]] for n, p in (("lr", lr_pd), ("lgbm", lgbm_pd))},
        bins,
    )
    targets = cfg["targets"]
    meets = {
        name: m["test"]["auc"] >= targets["auc_min"] and m["test"]["ece"] <= targets["ece_max"]
        for name, m in models.items()
    }
    report_json = {
        "targets": targets,
        "meets_targets": meets,
        "selected": selected,
        "selection_rule": "lower test Brier, then higher test AUC",
        "provenance": provenance,
        "models": models,
        "test_reliability": {
            "lr": metrics.reliability(y[masks["test"]], lr_pd[masks["test"]], bins),
            "lgbm": metrics.reliability(y[masks["test"]], lgbm_pd[masks["test"]], bins),
        },
    }
    _write_json(out / "metrics.json", report_json)
    model_card = {
        "version": versions[selected],
        "selected": selected,
        "versions": versions,
        "artefacts": {"lr": ["scorecard.json"], "lgbm": ["lgbm.txt", "calibrator.json", "scorecard.json"]},
        "target": "buyer does not pay within 60 days after the due date, or dilution above 20% (synthetic)",
        "features": list(FEATURES),
        "monotone_constraints": {f: MONOTONE[f] for f in FEATURES},
        "medians": medians,
        "lightgbm": {"best_iteration": int(booster.best_iteration), "params": cfg["lightgbm"]["params"]},
        "calibration": {"method": calibrator["method"], "validation_brier": calibrator["validation_brier"]},
        "metrics": {name: m["test"] for name, m in models.items()},
        "meets_targets": meets,
        "provenance": provenance,
        "limitations": [
            "labels are synthetic, drawn from a known latent model (training/README.md)",
            "with recourse assumed; no real bureau or KYC data",
            "few tier-A defaults in training, so low PDs carry wide estimation error",
        ],
    }
    _write_json(out / "model_card.json", model_card)
    return {"card": card, "metrics": report_json, "model_card": model_card}


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    root = synth.REPO_ROOT
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=root / cfg["data"])
    parser.add_argument("--out", type=Path, default=root / cfg["model_dir"])
    parser.add_argument("--version-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)
    result = train(args.data, args.out, args.version_date, cfg)
    print(f"selected: {result['metrics']['selected']} ({result['model_card']['version']})")
    for name, parts in result["metrics"]["models"].items():
        for part, m in parts.items():
            print(f"{name:5s} {part:10s} " + " ".join(f"{k} {v}" for k, v in m.items()))
    print(f"wrote {args.out}")
    return 0 if math.isfinite(result["card"]["intercept"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
