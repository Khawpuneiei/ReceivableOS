# policy-ai training

Everything here runs offline and is for training only. The service never imports it.

```bash
pip install -r services/policy-ai/requirements-train.txt
cd services/policy-ai
PYTHONPATH=.:../.. python -m training.synth            # writes data/training/synthetic_invoices.csv
PYTHONPATH=.:../.. python -m training.train            # writes model/ (generates the CSV first if it is missing)
```

## Synthetic invoices (`synth.py`, `synth_config.yaml`)

No labelled SME invoice defaults exist for this build, so the credit model trains on **openly synthetic** data drawn from a known latent model (brief section 8.3). Every number lives in `synth_config.yaml`, so Finance can tune the ranges without touching code; values marked FINANCE-TBD wait for their Oct 11 sign-off.

- **Size:** 20,000 THB invoices, 300 buyers, 800 suppliers, 24 monthly cohorts (2024-10 to 2026-09).
- **Buyers:** a latent credit quality bucketed with noise into tiers A/B/C/D (30/40/22/8%), with an `internal_rating` consistent with the tier. Late-payment rates are beta-distributed by tier (means 3/8/15/30%), and `avg_days_late` follows the late rate. Limits and sectors are per buyer. About 70% of invoices are buyer-confirmed.
- **Suppliers:** years trading 0-30, invoices financed and paid on time, historical default rate (mostly 0), dilution 0-10%, higher for suppliers that sell mostly to retail.
- **Invoices:** log-normal amounts (median 400,000, clipped to 20,000-5,000,000), tenor 15-120 days peaked at 30/45/60/90, invoice age 0-60 days, OCR confidence and fraud score.
- **Gaps:** a few profile keys are left out on purpose (`avg_days_late` 5%, `dilution_rate` 4%, `historical_default_rate` 4%), so imputation is exercised.
- **Drift:** late rates are 15% higher in the last 6 cohorts, so the time split (train 1-16, validation 17-20, test 21-24) is meaningful.
- **Labels:** `logit p = intercept + sum(beta_i x_i) + 0.12 x tier x tenor/30 + N(0, 0.3)` and `y ~ Bernoulli(p)`. `y = 1` stands for "not paid within 60 days after the due date, or diluted by more than 20%". `latent_p` is stored next to `y`.
- **Calibration of the generator:** the intercept is set so the shared demo profile (Siam Fresh Pack -> Mekong Basket Retail, tier A, confirmed, 34-day tenor) has a noise-free latent PD of 0.0027, close to Finance's happy path. The other betas were then set for a ~4% base rate. The unconfirmed-buyer variant (V3) has latent PD 0.0044, and the repeat-seller scenario 8 has 0.0034. These are the generator's truths; a trained model only estimates them.

Rows carry the raw profile keys of brief section 5.3 (`supplier.*`, `buyer.*`), the invoice fields the model reads, `cohort`, `latent_p` and `y`, so every row goes through the service's own `app/profiles.py`.

| | |
|---|---|
| Seed | `20261010` |
| Config sha256 | `b62245ef08457fa67b7b0b8fcc2bd8cbb4f72715637bfd015a5360222423a9e3` |
| CSV sha256 (numpy 2.5, pandas 3.0) | `633706e5f84b5767c34fbbc7357d03de2482873f307ba145388a0ef839aea71c` |
| Output | `data/training/synthetic_invoices.csv` at the repo root, 4.1 MB, git-ignored and regenerated from the seed |
| Base rate | 4.16% (tier A 0.40%, B 1.58%, C 5.27%, D 29.5%) |
| Runtime | well under a second |

`data/` is git-ignored except `data/invoices/`, so this README lives here and not beside the CSV.

## Features and the scorecard baseline (`train.py`, `train_config.yaml`)

- **Features:** `app/features.py::build_features` is the one function training and serving share. It builds 16 features plus a 5-level sector one-hot (`other` is the baseline): tier, late rate, days late, confirmed, log relationship months, log supplier years, log invoices financed, historical default rate, dilution, on-time ratio, log amount, tenor, invoice age, amount / buyer limit, OCR confidence and fraud score. It is pure Python, so serving needs no numpy.
- **Missing values:** a gap takes the median of the buyer's tier, from the train split. The medians are saved with the model. A buyer with no tier is scored with tier C's medians (`missing_tier`).
- **Time split:** train cohorts 1-16 (13,290 rows), validation 17-20 (3,261), test 21-24 (3,449, drifted).
- **Baseline:** standardised L2 logistic regression (C = 1). It is saved as a points scorecard in `model/scorecard.json` (600 points at 50:1 good:bad odds, PDO 20). The file holds the coefficients, means, scales, points per unit, tier medians and provenance hashes. It is plain JSON, read by `app/scorecard.py` without numpy or sklearn.
- **Metrics:** `training/metrics.py` computes AUC, PR-AUC, Brier, ECE (10 equal-width bins) and KS, written to `model/metrics.json`.

| LR scorecard | AUC | PR-AUC | Brier | ECE | KS |
|---|---|---|---|---|---|
| validation | 0.8397 | 0.3376 | 0.0319 | 0.0059 | 0.544 |
| test | 0.8455 | 0.2906 | 0.0416 | 0.0158 | 0.560 |

Targets: AUC at least 0.75 and ECE at most 0.03. The scorecard meets both.
