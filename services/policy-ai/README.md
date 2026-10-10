# policy-ai

Owner: Policy AI engineer. Scope: financing policy, credit risk model.

Endpoint: `POST /policy/decide` on port 8002, plus `GET /health`. Request and response models are in [`shared/schemas.py`](../../shared/schemas.py).

Design doc: [`docs/04-policy-ai.md`](../../docs/04-policy-ai.md). Assistant instructions for this service: `CLAUDE.md` in this folder (added by the service owner).

Status: rule engine live with a placeholder PD model (`scorecard-fallback`). Endpoints: `POST /policy/decide`, `GET /policy/rules`, `GET /health`.

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

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `POLICY_RULES_PATH` | `rules/policy.v1.yaml` | Rule set to load at startup. |
| `POLICY_DEFAULT_MANDATE_FILE` | `rules/default_mandate.json` | Mandate applied when a request carries none (the demo mandate: advance at most 70%, APR at most 12%, PD at most 5%, review at or above THB 837,500, THB 1.5m per transaction, THB 3m a day). It shows up as `MANDATE.DEFAULT` in `reasons` and `rule_trace`. A mandate in the request always wins. The file is checked against the platform maxima in `mandate_limits` at startup, so it can only tighten terms; its money caps apply only to invoices in its `allowed_currency`. |
