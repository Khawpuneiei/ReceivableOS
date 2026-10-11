# policy-ai

Owner: Policy AI engineer. Scope: financing policy, credit risk model.

Endpoint: `POST /policy/decide` on port 8002, plus `GET /health`. Request and response models are in [`shared/schemas.py`](../../shared/schemas.py).

Design doc: [`docs/04-policy-ai.md`](../../docs/04-policy-ai.md). Assistant instructions for this service: `CLAUDE.md` in this folder (added by the service owner).

Status: rule engine live with the trained PD model (`credit-lr-2026-10-10.2`, the LR scorecard). Endpoints: `POST /policy/decide`, `GET /policy/rules`, `GET /health`.

## Run

From the repo root, with `.env` in place:

```bash
pip install -r services/policy-ai/requirements.txt
python -m uvicorn app.main:app --app-dir services/policy-ai --port 8002 --reload
```

## Test

```bash
pytest services/policy-ai
ruff check services/policy-ai
```

## Implementation progress

Built feature by feature.

- `app/schemas.py`: `PolicyRequestExt` and `PolicyDecisionExt` subclass the shared contract and only add optional request fields (`mandate`, `portfolio`, `as_of_date`) and extra response fields. The input `Mandate` uses the agent wallet's key names, accepts their aliases (`max_advance_rate`, `max_pd`, `human_review_above_thb`, `currency`) and ignores wallet-only keys.
- `app/profiles.py`: turns the free-form `supplier_profile` / `buyer_profile` dicts into typed profiles (aliases, rating to tier A-D). Absent fields stay `MISSING` so rules skip them instead of guessing; malformed values raise `ValueError`.
- `rules/policy.v1.yaml` + `app/rules.py`: the credit rule set (`credit-policy-v0.1`) and its strict loader. Every section and every rule's `param` block is validated at import, so a typo stops the service from starting. `check_registry()` fails when the YAML and the Python predicates disagree. Set `POLICY_RULES_PATH` to load another file (tests use temp copies). `REVIEW.LARGE_TICKET` ships switched off (`param.enabled: false`) so the wallet's own human-approval path stays reachable.
- `app/engine.py` (part 1): the rule engine context (`Ctx`: invoice, normalised profiles, mandate, portfolio, `as_of`, tenor and age), the predicate registry, the hard rules and the pre-model knock-outs. Every rule runs and all hits are collected; reject beats review beats approve; rules with missing inputs are traced as `skip(missing)`. Hit messages carry only YAML text and numbers, never invoice text. `engine.PENDING` lists the YAML ids whose predicates arrive with the later stages.
- `app/model.py` (placeholder) + PD gates and review triggers in `app/engine.py`: a fixed logistic PD (`model_version` `scorecard-fallback`; PD 0.0029 on the demo, 0.0048 when the buyer hasn't confirmed) until the trained model lands. PD above 0.15 rejects (`KO.PD_TOO_HIGH`); PD above min(0.05, the mandate's `max_predicted_default`) reviews (`REVIEW.PD_ABOVE_CAP`). Review triggers: unconfirmed buyer, fraud flags no knock-out handles, line items that don't sum (± VAT), fewer than 3 financed invoices, thin buyer profile (terms then use tier C), and the large-ticket check (off by default).
- `app/terms.py` + the terms stage in `app/engine.py`: base advance by tier, haircuts, floor, mandate cap, then the buyer, facility, single-invoice and mandate per-transaction caps; the rate is floored to 4 dp and the limit to the cent, so the limit never exceeds a cap. Pricing: annual risk price (cost of funds + margin + PD x LGD x 365 / max(tenor, 60) + unconfirmed premium), fee per 30 days rounded up to 0.0005 and clamped to [0.005, 0.0123], APR via `shared/money.py`. Rules that need terms run last: `KO.NO_HEADROOM`, `KO.PRICING` (on the unclamped price), `REVIEW.MANDATE_APR`, `REVIEW.CONCENTRATION`. Demo: advance 0.70, limit 524300.00, fee 0.009 (10.95% APR), fee amount 5347.86.
- `app/decision.py` + `app/hashing.py` + `app/main.py`: `POST /policy/decide` returns the shared `PolicyDecision` plus the policy fields (`decision_id`, `pd`, `expected_loss`, `tenor_days`, `apr`, `fee_amount`, `reason_details`, `rule_trace`, `valid_until`, `decision_hash`, `request_hash`, `as_of_date`). A reject carries zero terms; a review carries the terms that would apply. Invalid input (non-positive amount, malformed profile, unknown tier, out-of-range mandate) returns 422. `GET /policy/rules` returns the active rule set. `decision_hash` is keccak256 over the canonical JSON of the shared `PolicyDecision` fields without `decision_hash`, the same check the agent wallet runs (open PR #17); policy-only fields are outside it. Logs carry ids and the outcome only. No LLM is called on this path.
- `fixtures/` + `tests/test_scenarios.py`: demo scenarios 1-8 from the brief (section 11) as full `/policy/decide` bodies in `fixtures/requests/` (THB demo mandate in `fixtures/mandates/demo_thb.json`, `as_of_date` 2026-10-12) with the expected decision, terms and reason codes in `fixtures/expected/`. Results: 1 approve 0.70 / 524300.00 / 0.009; 2 reject `KO.PO_MISMATCH`; 3 review 0.60 / 449400.00 / 0.012; 4 review `HARD.INJECTION` with the happy-path terms; 5 reject `KO.DUPLICATE`; 6 reject `HARD.FRAUD_SCORE`; 7 reject `KO.KYC_INVALID`; 8 approve with the dilution haircut (0.75 before the 0.70 mandate cap) and facility headroom 2475700.00; 8b (no mandate, default mandate off) approve 0.75 / 561750.00. The tests also check the response invariants, a repeat gives the same hash, and that lowering one YAML number (`REVIEW.PD_ABOVE_CAP` `review_above`) turns scenario 1 into review.
- `training/synth.py` + `training/synth_config.yaml`: seeded synthetic invoices for the credit model (200,000 rows, 24 cohorts, ~4% base rate, late-rate drift in the last 6 cohorts) written to the git-ignored `data/training/`. Training needs `requirements-train.txt`; serving does not. See [`training/README.md`](training/README.md).
- `app/features.py` + `app/scorecard.py` + `training/train.py`: the shared feature builder and the logistic-regression scorecard baseline (`model/scorecard.json`, plain JSON). Test AUC 0.8909, ECE 0.0018 (revision 2).
- `training/train.py` (part 2): calibrated LightGBM next to the scorecard, with `model/lgbm.txt` (text format), `model/calibrator.json`, `model/model_card.json`, `model/metrics.json` and `model/reliability.png`. No pickle. Test split (revision 2): LR AUC 0.8909 / Brier 0.0338 / ECE 0.0018; LightGBM AUC 0.8873 / Brier 0.0343 / ECE 0.0047. The LR scorecard is selected (lower test Brier).
- `app/model.py`: serves the model `model/model_card.json` selects (now the LR scorecard `credit-lr-2026-10-10.2`, read as plain JSON). Fallback chain: the selected model; `scorecard.json` as `scorecard-fallback` (for example when LightGBM is selected but the optional `lightgbm` package isn't installed); then the fixed placeholder as `placeholder-fallback`. A scoring error also drops to the placeholder, so the endpoint never returns 500. Decisions now carry `top_features` (top 3 drivers in log-odds), a `MODEL.PD` reason and one `MODEL.*` reason per driver. Serving needs only `requirements.txt`. p95 latency of `/policy/decide` is about 5 ms through the test client. Revision 2 of the model (200,000 training rows and a tier x tenor term, see [`training/README.md`](training/README.md#tuning-for-the-demo-pd-windows-revision-2)) puts the demo at PD 0.0027, V3 at 0.00463 and scenario 8 at 0.00337, so all three price as Finance expects (fees 0.009, 0.012, 0.009).

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `POLICY_RULES_PATH` | `rules/policy.v1.yaml` | Rule set to load at startup. |
| `POLICY_MODEL_DIR` | `model/` | Folder with `model_card.json`, `scorecard.json` and, for LightGBM, `lgbm.txt` + `calibrator.json`. A missing or broken folder falls back to the scorecard, then the placeholder. |
| `POLICY_DEFAULT_MANDATE_FILE` | `rules/default_mandate.json` | Mandate applied when a request carries none (the demo mandate: advance at most 70%, APR at most 12%, PD at most 5%, review at or above THB 837,500, THB 1.5m per transaction, THB 3m a day). It shows up as `MANDATE.DEFAULT` in `reasons` and `rule_trace`. A mandate in the request always wins. The file is checked against the platform maxima in `mandate_limits` at startup, so it can only tighten terms; its money caps apply only to invoices in its `allowed_currency`. |
