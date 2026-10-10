"""Seeded synthetic invoice generator for the credit model (services/policy-ai/CLAUDE.md section 8.3).

No labelled SME invoice defaults exist for this build, so invoices are drawn from a known latent logistic
model and labelled from it. Every parameter lives in training/synth_config.yaml. Rows carry the raw
profile keys of section 5.3 (prefixed `supplier.` / `buyer.`), the invoice fields the model uses,
`cohort`, the latent probability `latent_p` and the label `y`.

Run from services/policy-ai:  PYTHONPATH=.:../.. python -m training.synth [--n N] [--out PATH]
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

SERVICE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_DIR.parents[1]
CONFIG_PATH = Path(__file__).resolve().parent / "synth_config.yaml"
TIERS = ("A", "B", "C", "D")


def load_config(path: Path = CONFIG_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def config_sha256(path: Path = CONFIG_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def latent_logit(x: dict[str, Any], cfg: dict) -> Any:
    """The labelling model, without noise. Works on scalars or numpy arrays.

    x keys: tier_ord, late_payment_rate, avg_days_late, confirmed, relationship_months, years_in_business,
    invoices_financed, historical_default_rate, dilution_rate, on_time_ratio, amount, tenor_days,
    invoice_age_days, buyer_limit, ocr_confidence, fraud_score, sector.
    """
    lat, b = cfg["latent"], cfg["latent"]["beta"]
    sector = np.asarray(x["sector"])
    sector_effect = np.zeros(sector.shape)
    for name, value in lat["sector"].items():
        sector_effect = np.where(sector == name, value, sector_effect)
    return (
        lat["intercept"]
        + b["tier_ord"] * x["tier_ord"]
        + b["late_payment_rate"] * x["late_payment_rate"]
        + b["avg_days_late"] * x["avg_days_late"]
        + b["confirmed"] * x["confirmed"]
        + b["log1p_relationship_months"] * np.log1p(x["relationship_months"])
        + b["log1p_years_in_business"] * np.log1p(x["years_in_business"])
        + b["log1p_invoices_financed"] * np.log1p(x["invoices_financed"])
        + b["historical_default_rate"] * x["historical_default_rate"]
        + b["dilution_rate"] * x["dilution_rate"]
        + b["on_time_ratio"] * x["on_time_ratio"]
        + b["log_amount_centred"]
        * np.log(np.asarray(x["amount"], dtype=float) / cfg["invoices"]["amount_median"])
        + b["tenor_days"] * x["tenor_days"]
        + b["invoice_age_days"] * x["invoice_age_days"]
        + b["amount_to_buyer_limit"]
        * np.asarray(x["amount"], dtype=float)
        / np.asarray(x["buyer_limit"], dtype=float)
        + b["ocr_confidence"] * x["ocr_confidence"]
        + b["fraud_score"] * x["fraud_score"]
        + b["tier_x_tenor_30d"] * np.asarray(x["tier_ord"]) * np.asarray(x["tenor_days"]) / 30
        + sector_effect
    )


def latent_pd(x: dict[str, Any], cfg: dict | None = None) -> float:
    """Noise-free latent PD for one invoice (sigmoid of latent_logit)."""
    z = float(latent_logit(x, cfg or load_config()))
    return 1.0 / (1.0 + np.exp(-z))


def _cohort_start(first: str, k: int) -> date:
    year, month = (int(p) for p in first.split("-"))
    month += k
    return date(year + (month - 1) // 12, (month - 1) % 12 + 1, 1)


def _beta_from_mean(rng: np.random.Generator, mean: np.ndarray, concentration: float) -> np.ndarray:
    return rng.beta(mean * concentration, (1 - mean) * concentration)


def _buyers(rng: np.random.Generator, cfg: dict) -> pd.DataFrame:
    c, n = cfg["buyers"], cfg["n_buyers"]
    quality = rng.normal(size=n)
    noisy = quality + rng.normal(scale=c["latent_noise_sd"], size=n)
    shares = np.array([c["tier_shares"][t] for t in TIERS])
    cuts = np.quantile(noisy, 1 - np.cumsum(shares)[:-1])  # descending: top 30% -> A, next 40% -> B ...
    tier_ord = sum((noisy < cut).astype(int) for cut in cuts)
    tiers = np.array(TIERS)[tier_ord]
    ratings = np.array([rng.choice(c["ratings"][t]) for t in tiers])
    late_mean = np.array([c["late_rate_mean"][t] for t in tiers])
    late = _beta_from_mean(rng, late_mean, c["late_rate_concentration"])
    limit = np.array([c["limit_median"][t] for t in tiers]) * np.exp(
        rng.normal(scale=c["limit_sd_log"], size=n)
    )
    sectors = list(c["sectors"])
    sector = rng.choice(sectors, size=n, p=[c["sectors"][s] for s in sectors])
    return pd.DataFrame(
        {
            "buyer_id": [f"B{i:04d}" for i in range(n)],
            "tier_ord": tier_ord,
            "internal_rating": ratings,
            "late_base": late,
            "days_late_noise": np.exp(rng.normal(scale=c["days_late_noise_sd"], size=n)),
            "buyer_limit": np.round(limit, -4),
            "relationship_months": rng.integers(0, c["relationship_months_max"] + 1, size=n),
            "sector": sector,
            "confirmed_share": [c["confirmed_share"][t] for t in tiers],
        }
    )


def _suppliers(rng: np.random.Generator, cfg: dict) -> pd.DataFrame:
    c, n = cfg["suppliers"], cfg["n_suppliers"]
    years = np.minimum(rng.gamma(c["years_gamma_shape"], c["years_gamma_scale"], size=n), c["years_max"])
    years = np.floor(years).astype(int)
    financed = rng.poisson(years * c["financed_per_year"])
    total = financed + rng.poisson(np.maximum(years, 1) * c["invoices_total_per_year"]) + 1
    on_time = rng.binomial(total, rng.beta(*c["on_time_beta"], size=n))
    hist = np.where(
        rng.random(n) < c["historical_default_share_zero"],
        0.0,
        rng.beta(*c["historical_default_beta"], size=n),
    )
    retail_focused = rng.random(n) < c["retail_focused_share"]
    dilution = rng.beta(*c["dilution_beta"], size=n) + retail_focused * c["dilution_retail_bump"]
    facility = c["facility_median"] * np.exp(rng.normal(scale=c["facility_sd_log"], size=n))
    return pd.DataFrame(
        {
            "supplier_id": [f"S{i:04d}" for i in range(n)],
            "years_trading": years,
            "invoices_financed_count": financed,
            "invoices_total": total,
            "paid_on_time": on_time,
            "historical_default_rate": np.round(hist, 4),
            "dilution_rate": np.round(np.minimum(dilution, 0.10), 4),
            "retail_focused": retail_focused,
            "facility_limit": np.round(facility, -4),
            "kyc_valid": rng.random(n) < c["kyc_valid_share"],
        }
    )


def _tenor(rng: np.random.Generator, c: dict, n: int) -> np.ndarray:
    peaks = rng.choice(c["tenor_peaks"], size=n, p=c["tenor_peak_weights"])
    tenor = np.rint(peaks + rng.normal(scale=c["tenor_jitter_sd"], size=n)).astype(int)
    return np.clip(tenor, c["tenor_min"], c["tenor_max"])


def generate(cfg: dict, n: int | None = None) -> pd.DataFrame:
    """All rows for the config, seeded. `n` overrides n_invoices (tests use a small N)."""
    rng = np.random.default_rng(cfg["seed"])
    n = n or cfg["n_invoices"]
    buyers, suppliers = _buyers(rng, cfg), _suppliers(rng, cfg)
    inv = cfg["invoices"]

    supplier_idx = rng.integers(0, len(suppliers), size=n)
    s = suppliers.iloc[supplier_idx].reset_index(drop=True)
    retail_buyers = np.flatnonzero(buyers["sector"].to_numpy() == "retail")
    wants_retail = s["retail_focused"].to_numpy() & (
        rng.random(n) < cfg["suppliers"]["retail_buyer_share_if_focused"]
    )
    buyer_idx = np.where(
        wants_retail, rng.choice(retail_buyers, size=n), rng.integers(0, len(buyers), size=n)
    )
    b = buyers.iloc[buyer_idx].reset_index(drop=True)

    cohort = np.sort(rng.integers(0, cfg["n_cohorts"], size=n))
    drifted = cohort >= cfg["n_cohorts"] - cfg["drift"]["last_cohorts"]
    late = np.minimum(
        b["late_base"].to_numpy() * np.where(drifted, cfg["drift"]["late_rate_multiplier"], 1.0), 0.95
    )
    late = np.round(late, 4)
    days_late = np.round(late * cfg["buyers"]["days_late_per_late_rate"] * b["days_late_noise"].to_numpy(), 1)

    amount = np.exp(rng.normal(np.log(inv["amount_median"]), inv["amount_sd_log"], size=n))
    amount = np.round(np.clip(amount, inv["amount_min"], inv["amount_max"]), 2)
    tenor = _tenor(rng, inv, n)
    age = np.minimum(rng.geometric(1 / (inv["age_mean_days"] + 1), size=n) - 1, inv["age_max_days"])
    day_in_month = rng.integers(0, 28, size=n)
    starts = [_cohort_start(cfg["first_cohort"], int(k)) for k in cohort]
    issue = [st + timedelta(days=int(d)) for st, d in zip(starts, day_in_month, strict=True)]
    as_of = [i + timedelta(days=int(a)) for i, a in zip(issue, age, strict=True)]
    due = [a + timedelta(days=int(t)) for a, t in zip(as_of, tenor, strict=True)]

    confirmed = rng.random(n) < b["confirmed_share"].to_numpy()
    confidence = np.round(rng.beta(*inv["confidence_beta"], size=n), 3)
    fraud = np.round(rng.beta(*inv["fraud_score_beta"], size=n), 3)
    buyer_limit = b["buyer_limit"].to_numpy()
    on_time_ratio = s["paid_on_time"].to_numpy() / s["invoices_total"].to_numpy()

    x = {
        "tier_ord": b["tier_ord"].to_numpy(),
        "late_payment_rate": late,
        "avg_days_late": days_late,
        "confirmed": confirmed.astype(float),
        "relationship_months": b["relationship_months"].to_numpy(),
        "years_in_business": s["years_trading"].to_numpy(),
        "invoices_financed": s["invoices_financed_count"].to_numpy(),
        "historical_default_rate": s["historical_default_rate"].to_numpy(),
        "dilution_rate": s["dilution_rate"].to_numpy(),
        "on_time_ratio": on_time_ratio,
        "amount": amount,
        "tenor_days": tenor,
        "invoice_age_days": age,
        "buyer_limit": buyer_limit,
        "ocr_confidence": confidence,
        "fraud_score": fraud,
        "sector": b["sector"].to_numpy(),
    }
    logit = latent_logit(x, cfg) + rng.normal(scale=cfg["latent"]["noise_sd"], size=n)
    p = 1 / (1 + np.exp(-logit))
    y = (rng.random(n) < p).astype(int)

    exp_share = cfg["invoices"]["exposure_share_max"]
    rows = pd.DataFrame(
        {
            "invoice_id": [f"syn_{i:06d}" for i in range(n)],
            "cohort": cohort + 1,
            "cohort_month": [f"{st:%Y-%m}" for st in starts],
            "as_of_date": [d.isoformat() for d in as_of],
            "issue_date": [d.isoformat() for d in issue],
            "due_date": [d.isoformat() for d in due],
            "amount": amount,
            "currency": cfg["currency"],
            "confidence": confidence,
            "fraud_score": fraud,
            "supplier_id": s["supplier_id"],
            "supplier.years_trading": s["years_trading"],
            "supplier.invoices_financed_count": s["invoices_financed_count"],
            "supplier.invoices_total": s["invoices_total"],
            "supplier.paid_on_time": s["paid_on_time"],
            "supplier.historical_default_rate": s["historical_default_rate"],
            "supplier.dilution_rate": s["dilution_rate"],
            "supplier.kyc_valid": s["kyc_valid"],
            "supplier.current_exposure": np.round(
                rng.random(n) * exp_share * s["facility_limit"].to_numpy(), 2
            ),
            "supplier.facility_limit": s["facility_limit"],
            "buyer_id": b["buyer_id"],
            "buyer.internal_rating": b["internal_rating"],
            "buyer.on_time_payment_rate": np.round(1 - late, 4),
            "buyer.avg_days_late": days_late,
            "buyer.buyer_confirmed": confirmed,
            "buyer.relationship_months": b["relationship_months"],
            "buyer.sector": b["sector"],
            "buyer.current_exposure": np.round(rng.random(n) * exp_share * buyer_limit, 2),
            "buyer.buyer_limit": buyer_limit,
            "latent_p": np.round(p, 6),
            "y": y,
        }
    )
    for column, share in cfg["missing_shares"].items():
        rows.loc[rng.random(n) < share, column] = np.nan
    return rows


def profiles(row: dict) -> tuple[dict, dict, dict, date]:
    """(invoice fields, supplier_profile, buyer_profile, as_of) for one CSV row, keys as in section 5.3."""

    def present(prefix: str) -> dict:
        return {
            k.split(".", 1)[1]: v
            for k, v in row.items()
            if k.startswith(prefix) and v is not None and not (isinstance(v, float) and np.isnan(v))
        }

    invoice = {
        k: row[k] for k in ("amount", "currency", "issue_date", "due_date", "confidence", "fraud_score")
    }
    return invoice, present("supplier."), present("buyer."), date.fromisoformat(row["as_of_date"])


def write(rows: pd.DataFrame, out: Path) -> str:
    """Write the CSV and return its sha256."""
    out.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(out, index=False, lineterminator="\n")
    return hashlib.sha256(out.read_bytes()).hexdigest()


def summary(rows: pd.DataFrame) -> str:
    to_tier = {r: t for t, ratings in load_config()["buyers"]["ratings"].items() for r in ratings}
    tier = rows["buyer.internal_rating"].map(to_tier)
    lines = [f"rows {len(rows)}, base rate {rows['y'].mean():.4f}"]
    lines += [
        f"  tier {t}: share {(tier == t).mean():.3f}, default rate {rows.loc[tier == t, 'y'].mean():.4f}"
        for t in TIERS
    ]
    by_cohort = rows.groupby("cohort")["y"].mean()
    lines += [f"  cohort {c:2d}: default rate {r:.4f}" for c, r in by_cohort.items()]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=None, help="number of invoices (default from the config)")
    parser.add_argument("--out", type=Path, default=None, help="CSV path (default from the config)")
    args = parser.parse_args(argv)
    cfg = load_config()
    out = args.out or REPO_ROOT / cfg["output"]
    rows = generate(cfg, args.n)
    digest = write(rows, out)
    print(summary(rows))
    print(
        f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB), sha256 {digest}, config sha256 {config_sha256()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
