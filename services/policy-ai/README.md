# policy-ai

Owner: Policy AI engineer. Scope: financing policy, credit risk model.

Endpoint: `POST /policy/decide` on port 8002, plus `GET /health`. Request and response models are in [`shared/schemas.py`](../../shared/schemas.py).

Design doc: [`docs/04-policy-ai.md`](../../docs/04-policy-ai.md). Assistant instructions for this service: `CLAUDE.md` in this folder (added by the service owner).

Status: rule engine live with the trained PD model (`credit-lr-2026-10-10.2`, the LR scorecard). Endpoints: `POST /policy/decide`, `POST /policy/mandate/compile`, `GET /policy/rules`, `GET /health`.

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

## Train

Training is offline and optional; serving reads the committed files in `model/` and needs only `requirements.txt`.

```bash
python3 -m pip install -r services/policy-ai/requirements-train.txt
cd services/policy-ai
PYTHONPATH=.:../.. python -m training.synth     # 200,000 synthetic invoices -> data/training/ (git-ignored), ~4 s
PYTHONPATH=.:../.. python -m training.train     # LR scorecard + calibrated LightGBM -> model/, ~25 s
```

The data is **synthetic**, drawn from a known latent model (see [`training/README.md`](training/README.md)), so
these metrics show a correct, calibrated pipeline, not real-world accuracy. Test split = cohorts 21-24, the drifted
ones (33,335 rows, base rate 4.6%):

| Model | AUC | PR-AUC | Brier | ECE | KS | Served |
|---|---|---|---|---|---|---|
| LR scorecard `credit-lr-2026-10-10.2` | 0.8909 | 0.4083 | 0.03379 | 0.0018 | 0.627 | **yes** (lower test Brier) |
| LightGBM + isotonic `credit-lgbm-2026-10-10.2` | 0.8873 | 0.3927 | 0.03432 | 0.0047 | 0.611 | no |

Targets: AUC ≥ 0.75, ECE ≤ 0.03 (both met by both models). Demo PDs with the served model: scenario 1 0.0027,
scenario 3 0.00463, scenario 8 0.00337, all inside Finance's pricing windows; across 12 refits with different seeds
they stay inside (ranges in `training/README.md`). Re-running `training.train` on the same CSV gives byte-identical
files.

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
- `app/mandate.py`: `POST /policy/mandate/compile` turns the SME's sentence (`{"text", "mandate_id"?}`) into a mandate. A deterministic regex parser reads advance, APR, buyer-risk %, the human-review amount, per-transaction and daily caps, currency, payee addresses and validity. Every cap must be above 0 and at or under `mandate_limits` in the YAML; nothing is clamped. Wording that asks for no limit ("unlimited", "ignore all limits", "send everything"), an unregistered payee or an out-of-range value returns 422 with `{field, code, value, limit}` violations, never the text. Unmentioned caps take the platform defaults (`fields_from_defaults`). The compiled mandate is never looser than the sentence either: amounts are read with unit suffixes (k, m, mn, million, thousand, baht, บาท) before or after "per day" / "per invoice"; minimum wording ("at least", "no less than", "minimum", "80% or more") returns 422 `AMBIGUOUS_VALUE` rather than becoming a cap; an amount next to "per day" / "per invoice" the parser can't read returns 422 `UNPARSED_CAP`; any other unread number returns 422 `UNRECOGNISED_NUMBER`. The `mandate` object uses exactly the agent wallet's field names (PR #17: `payee_allowlist` as registry ids, `allowed_targets`, `valid_from`); the asset type, provenance hash and warnings sit in the envelope. `payee_allowlist` is always the whole payee registry in `rules/policy.v1.yaml` (the seller, both lenders and the platform fee account), even when the sentence names one payee: the sentence can only name payees that are already registered, never add or narrow them. The wallet currently accepts THB only, so a USD mandate compiles with a warning.
- `fixtures/profiles/` + `fixtures/requests/variants/` + `fixtures/expected/variants/`: the policy demo data set (brief 11.1). 5 sellers: Siam Fresh Pack, the same seller after V6/V7, a thin-file seller, a high-dilution seller and an expired-KYC seller. 5 buyers: Mekong Basket Retail PCL (A-) and fictional BBB, BB, B and unrated buyers. All tax IDs pass the Thai checksum. Also a strict mandate (`fixtures/mandates/strict_thb.*`, APR at most 10%) and 8 request variants with frozen expected decisions. The demo pair equals the orchestrator's `samples/profiles.json`, the OCR stub and docs/02 section 10 (tested).
- `app/llm_client.py` + `mandate.compile_text`: an optional LLM step for mandate phrasing the regex parser misses. `complete(messages, schema)` reads `LLM_PROVIDER` (`none`, `anthropic` or `openai`), `LLM_MODEL` and `LLM_API_KEY`, and uses the standard library's HTTP client (no SDK, 5 s timeout). It is asked only when the sentence has numbers the parser couldn't read, only for the caps the parser didn't find, and never when the text asks for no limit or states a minimum. An LLM value is used only if it equals one of those unread numbers (as a % or as an amount with its unit, in the field its "per day" / "per invoice" phrase names), so it can't invent or loosen a cap; otherwise the number stays a 422. The sentence goes in the user message between random delimiters, never in the system prompt. Every proposal goes through the same platform-limit checks as parsed values, so an LLM can't loosen a mandate (a proposal over a limit returns 422), and its fields are listed in `fields_from_llm`. With no provider, no model or the `.env.example` placeholder key (`replace-me`) the output is the same as the parser alone; a timeout, an error or a reply that isn't JSON falls back to the platform defaults with a warning. `/policy/decide` never imports the client (tested in a fresh process).

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `POLICY_RULES_PATH` | `rules/policy.v1.yaml` | Rule set to load at startup. |
| `POLICY_MODEL_DIR` | `model/` | Folder with `model_card.json`, `scorecard.json` and, for LightGBM, `lgbm.txt` + `calibrator.json`. A missing or broken folder falls back to the scorecard, then the placeholder. |
| `POLICY_DEFAULT_MANDATE_FILE` | `rules/default_mandate.json` | Mandate applied when a request carries none (the demo mandate: advance at most 70%, APR at most 12%, PD at most 5%, review at or above THB 837,500, THB 1.5m per transaction, THB 3m a day). It shows up as `MANDATE.DEFAULT` in `reasons` and `rule_trace`. A mandate in the request always wins. The file is checked against the platform maxima in `mandate_limits` at startup, so it can only tighten terms; its money caps apply only to invoices in its `allowed_currency`. |
| `LLM_PROVIDER` | `none` | `anthropic` or `openai` turns on the optional LLM step of `/policy/mandate/compile`. Anything else means no LLM. |
| `LLM_MODEL` | (empty) | Model name for that provider. Empty means no LLM. |
| `LLM_API_KEY` | (empty) | API key, from `.env` only. Empty or the `replace-me` placeholder means no LLM. |
