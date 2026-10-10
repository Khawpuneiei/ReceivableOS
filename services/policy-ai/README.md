# policy-ai

Owner: Policy AI engineer. Scope: financing policy, credit risk model.

Endpoint: `POST /policy/decide` on port 8002, plus `GET /health`. Request and response models are in [`shared/schemas.py`](../../shared/schemas.py).

Design doc: [`docs/04-policy-ai.md`](../../docs/04-policy-ai.md). Assistant instructions for this service: `CLAUDE.md` in this folder (added by the service owner).

Status: stub. The endpoint returns a fixed response that matches the contract so the end-to-end demo runs.

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

Built feature by feature; the endpoint above stays the stub until the decision engine is wired in.

- `app/schemas.py`: `PolicyRequestExt` and `PolicyDecisionExt` subclass the shared contract and only add optional request fields (`mandate`, `portfolio`, `as_of_date`) and extra response fields. The input `Mandate` uses the agent wallet's key names, accepts their aliases (`max_advance_rate`, `max_pd`, `human_review_above_thb`, `currency`) and ignores wallet-only keys.
- `app/profiles.py`: turns the free-form `supplier_profile` / `buyer_profile` dicts into typed profiles (aliases, rating to tier A-D). Absent fields stay `MISSING` so rules skip them instead of guessing; malformed values raise `ValueError`.
- `rules/policy.v1.yaml` + `app/rules.py`: the credit rule set (`credit-policy-v0.1`) and its strict loader. Every section and every rule's `param` block is validated at import, so a typo stops the service from starting. `check_registry()` fails when the YAML and the Python predicates disagree. Set `POLICY_RULES_PATH` to load another file (tests use temp copies). `REVIEW.LARGE_TICKET` ships switched off (`param.enabled: false`) so the wallet's own human-approval path stays reachable.
- `app/engine.py` (part 1): the rule engine context (`Ctx`: invoice, normalised profiles, mandate, portfolio, `as_of`, tenor and age), the predicate registry, the hard rules and the pre-model knock-outs. Every rule runs and all hits are collected; reject beats review beats approve; rules with missing inputs are traced as `skip(missing)`. Hit messages carry only YAML text and numbers, never invoice text. `engine.PENDING` lists the YAML ids whose predicates arrive with the later stages.
- `app/model.py` (placeholder) + PD gates and review triggers in `app/engine.py`: a fixed logistic PD (`model_version` `scorecard-fallback`; PD 0.0029 on the demo, 0.0048 when the buyer hasn't confirmed) until the trained model lands. PD above 0.15 rejects (`KO.PD_TOO_HIGH`); PD above min(0.05, the mandate's `max_predicted_default`) reviews (`REVIEW.PD_ABOVE_CAP`). Review triggers: unconfirmed buyer, fraud flags no knock-out handles, line items that don't sum (± VAT), fewer than 3 financed invoices, thin buyer profile (terms then use tier C), and the large-ticket check (off by default).
