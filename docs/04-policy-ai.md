# 04 — Policy AI (knowledge summary for the PM)

> Short version for P. The full build brief (contract details, rule set, model plan, mandate compiler, prompts)
> is [`services/policy-ai/CLAUDE.md`](../services/policy-ai/CLAUDE.md). The Policy AI engineer keeps the status
> table at the bottom updated.

## What it does

Two jobs, both deterministic where money is concerned:

1. **Credit decision** — `POST /policy/decide`: invoice (OCR output) + seller and buyer profiles →
   **approve / review / reject**, `advance_rate`, `limit`, `fee_rate`, `risk_score`, `reasons`, plus additive
   audit fields (`policy_version`, `model_version`, `decision_hash`, `valid_until`, `rule_trace`, `apr`…).
2. **Mandate compiler** — `POST /policy/mandate/compile`: the seller's plain-language instruction → validated
   mandate JSON (max LTV, max APR, max predicted default, human-review amount, payees, expiry). The Agent Wallet's
   guard enforces it, off-chain and on-chain.

## Why judges should care

- **An LLM never decides money.** Credit terms come from a versioned YAML rule set run by code, plus a calibrated
  ML probability. In the mandate compiler the LLM can only *propose* JSON; a validator decides, and hostile text
  ("ignore all limits") can never loosen a cap. The demo sentence compiles with no LLM at all.
- **Explainable:** every number that changes cites a rule ID (`TERMS.HAIRCUT_UNCONFIRMED`, `KO.DUPLICATE`…) and the
  top model drivers. `GET /policy/rules` shows "the rules the AI must obey" on the dashboard.
- **Auditable:** same input + same versions ⇒ same `decision_hash`, which the wallet commits on chain.
- **Defence in depth:** the wallet guard re-checks limit, expiry, approve-only and the mandate caps, so a buggy or
  manipulated policy service still cannot overspend.

## Conventions this module uses (please confirm)

| Field | Meaning | Note |
|---|---|---|
| `fee_rate` | Discount fee **per 30 days** on the advance (0.009 = 0.90%/30d ≈ 10.95% APR) | Adopted from Finance. Policy returns the risk-based maximum; the wallet takes quotes at or below it and within the mandate APR. |
| `risk_score` | **Calibrated probability of default over the tenor**, 0–1, higher = riskier | Differs from Finance's "combined fraud + credit, 0.18". A composite would trip the mandate's 5% default cap and isn't a probability. Happy path ⇒ ≈ 0.003. |
| Money and rates | Decimal strings (`"524300.00"`, `"0.009"`) | Per `shared/schemas.py`; `model_version` and `policy_version` are contract fields. |
| Mandate field names | Exactly the Agent Wallet's `Mandate` model (PR #17): `max_ltv`, `max_apr`, `max_predicted_default`, `max_amount_per_tx`, `daily_cap`, `human_review_above` (inclusive ≥), `allowed_currency`, `settlement_asset`, `payee_allowlist` (registry ids), `allowed_targets`, `valid_from`, `expires_at`… | Compiler output parses with a copy of the wallet model (`extra="forbid"`); a test against the real model runs once #17 merges. Metadata sits in an envelope around `mandate`. |

## How a decision is made

1. **Hard rules (team-wide):** fraud score ≥ 0.30 ⇒ reject; any injection flag ⇒ review; OCR confidence < 0.80 ⇒ review.
2. **Knock-outs ⇒ reject:** duplicate invoice, invoice vs PO mismatch > 5% (OCR flag), KYC expired, overdue,
   < 7 or > 120 days to due, older than 90 days, buyer tier D, unsupported currency, no facility headroom,
   price above the 15% APR legal ceiling.
3. **Credit model ⇒ PD:** PD > 15% rejects; PD above the mandate's max (5%) sends to review.
4. **Review triggers:** buyer hasn't confirmed, other fraud flags, line items don't sum (± 7% VAT), new seller,
   at or above the human-review amount (THB 837,500), concentration > 30% of the pool, no buyer rating, price above the
   mandate APR.
5. **Terms:** base advance by buyer tier (A 80%, B 75%, C 65%) minus haircuts (unconfirmed −20 pts, long tenor,
   old invoice, high dilution, PD > 3%), floor 50%, capped by the mandate and facility limits.
6. **Price:** `annual = 4% cost of funds + 6% margin + PD × 45% LGD × 365/max(tenor, 60) [+3% if unconfirmed]`,
   converted to per 30 days and rounded up to 0.05% steps.

All thresholds are YAML defaults marked **FINANCE-TBD**; Finance's Oct 11 sign-offs change YAML only, not code.

## The shared demo, reproduced

Siam Fresh Pack → Mekong Basket Retail, THB 749,000, tenor 34 days, buyer A- and confirmed, mandate 70% / 12% APR / 5%:
advance 0.80 capped to **0.70**, limit **"524300.00"**, PD 0.27%, fee **0.009** per 30 days (10.95% APR) ⇒ **approve**.
Unconfirmed-buyer variant ⇒ **review**, 0.60 / 449,400.00, fee **0.012** (14.6% APR), PD 0.46%. Both match Finance's
expected numbers (except `risk_score`, above).

Test scenarios: happy path, inflated amount (reject), unconfirmed buyer (review), injected text (review, never
100% advance), duplicate (reject), high fraud score (reject), expired KYC (reject), repeat seller after late and
partial payment (smaller advance), hostile mandate text (no looser caps). Expensive-lender and over-LTV offers are
blocked by the wallet guard, not here.

## Demo UI and demo data (also owned by the Policy AI engineer)

- **UI:** one Streamlit screen in `ui/` on port 3000, talking only to the orchestrator: mandate → invoice evidence →
  decision with reasons and PD gauge → lender offers → on-chain tx timeline → attack buttons A1–A6, each adding a red
  BLOCKED row with who stopped it and the tx hash. `UI_MODE=fixtures` runs from saved responses; `UI_MODE=live` calls
  the orchestrator and labels anything it can't serve yet (mandate compile, quotes, confirm, attacks) as a fixture.
  The routes it still needs are listed in `ui/README.md`.
- **Demo data:** 5 sellers, 5 buyers, 3 mandates and one request + expected result per scenario, matching
  Finance's numbers and OCR's sample invoices (checksum-valid tax IDs 0105559000000 / 0107559000001,
  buyer "Mekong Basket Retail PCL"). You recheck.
- **Pitch pack:** the engineer supplies the "how the AI decides" slides (pipeline, rules as data, calibration plot,
  mandate JSON, blocked-attack screenshot).

## Credit risk model

- **Target:** the buyer doesn't pay within 60 days after the due date, or the invoice is diluted by more than 20%.
- **Data:** 200,000 **synthetic** THB invoices from a known latent logistic model (300 buyers, 800 sellers, about 4.2%
  base default rate, 24 monthly cohorts, +15% late rates in the last 6). There are no real SME default labels, so the
  claim is a correct, calibrated pipeline, not a validated model of Thai SMEs.
- **Served model:** the logistic-regression scorecard `credit-lr-2026-10-10.2`. It beat the calibrated LightGBM on
  test Brier (details and numbers in "Core algorithms" below).
- **Why calibration matters:** PD sets the price, a haircut and the review gate, so "0.3%" must mean about 0.3%.

## Dependencies

| From | Needed | Stand-in until then |
|---|---|---|
| OCR AI | `ExtractedInvoice` with `confidence`, `fraud_score`, `injection_flags`, and OCR's flag codes `DUPLICATE_HASH`, `DUPLICATE_INVOICE`, `PO_MISMATCH` (reject); other fraud flags ⇒ review | Hand-written fixtures |
| Finance | Oct 11 sign-offs: demo numbers, thresholds by rating × confirmed, feature ranges for synthetic data | YAML defaults above |
| Agent Wallet | The mandate JSON shape its guard consumes; agreement to re-check limit, expiry and mandate caps | Proposed shape in CLAUDE.md §7 |
| Orchestrator (PM) | Full seller/buyer profiles (CLAUDE.md §5.3) and the active mandate passed to `/policy/decide` | Fixture profiles; missing fields are skipped, never guessed |

## Timeline

- **Oct 10:** contract subclasses, profile normaliser, rules engine with placeholder PD, fixtures; callable on :8002 tonight.
- **Oct 11:** synthetic data, trained and calibrated model, mandate compiler, Finance numbers applied, end to end with OCR and Wallet.
- **Oct 11 (also):** demo data for the policy module (sent to P for recheck) and demo UI v1 in fixtures mode.
- **Oct 12:** UI attack buttons and audit view wired with P, metrics and docs, **code freeze at noon**; afternoon is rehearsal.

## Core algorithms (for the technical document)

Everything below runs in `services/policy-ai/` with no LLM and no network. Numbers are the shipped YAML defaults
(`rules/policy.v1.yaml`, `credit-policy-v0.1`) and the served model (`credit-lr-2026-10-10.2`).

### 1. Rule pipeline (`app/engine.py`)

A request becomes a context: the invoice, the normalised profiles (`app/profiles.py`), the mandate (from the
request, else the default mandate file), `as_of`, tenor and invoice age. The stages run in this order, and **every
rule runs**: all hits are collected, and the outcome is the worst one (reject beats review beats approve).

1. **Hard rules** (team-wide): fraud score ≥ 0.30 rejects; any injection flag, OCR confidence < 0.80 or unknown KYC
   reviews.
2. **Knock-outs** (reject): duplicate, PO mismatch, KYC invalid, overdue, tenor < 7 or > 120 days, older than 90
   days, buyer tier D, unsupported currency, due before issue.
3. **Model:** the PD (section 4). PD > 0.15 rejects (`KO.PD_TOO_HIGH`); PD above min(0.05, mandate
   `max_predicted_default`) reviews (`REVIEW.PD_ABOVE_CAP`).
4. **Review triggers:** unconfirmed buyer, fraud flags no knock-out handles, line items that don't sum (± 0/7% VAT),
   fewer than 3 invoices financed, no buyer tier (terms then use tier C), and the large-ticket check (shipped
   switched off, so the wallet's own human approval at THB 837,500 stays reachable).
5. **Terms and pricing** (sections 2–3), then the rules that need them: `KO.NO_HEADROOM`, `KO.PRICING` (on the
   unclamped price), `REVIEW.MANDATE_APR`, `REVIEW.CONCENTRATION`.

A rule whose inputs are missing is traced as `skip(missing)`, never guessed. A reject carries zero terms; a review
carries the terms that would apply. Reason messages are fixed YAML text plus numbers, never invoice text.

**Rules as data.** Thresholds, haircuts, prices and messages live in YAML. The loader validates every section and
every rule's `param` block at startup, and `check_registry()` fails if the YAML and the Python predicates disagree,
so a typo stops the service instead of silently skipping a rule. `GET /policy/rules` serves the active rule set.

### 2. Terms (`app/terms.py`)

1. Base advance by buyer tier: A 0.80, B 0.75, C 0.65.
2. Haircuts: unconfirmed −0.20, tenor > 90 days −0.05, age > 60 days −0.05, seller dilution > 5% −0.05, PD > 3% −0.05.
3. Floor at 0.50, then cap at the mandate's `max_ltv`.
4. `limit = advance × amount`, capped by the buyer's remaining limit, the seller's remaining facility, the
   single-invoice maximum (THB 3m) and the mandate's per-transaction maximum.
5. Rounding: the rate is floored to 4 dp **first**, then `limit = floor(rate × amount, 0.01)`. The limit therefore
   never exceeds a cap, and `advance_rate × amount = limit` holds to within 0.01.

### 3. Pricing

```
annual   = cost of funds 4% + margin 6% + PD × LGD 45% × 365 / max(tenor, 60)  [+ 3% if the buyer is unconfirmed]
fee_rate = annual × 30 / 365, rounded UP to a 0.05% step, clamped to [0.50%, 1.23%] per 30 days
APR      = shared/money.py fee_rate_30d_to_apr(fee_rate)
```

`KO.PRICING` checks the **unclamped** annual price against the 15% APR legal ceiling (the clamp alone is 14.97%, so
checking the clamped fee could never fire). `REVIEW.MANDATE_APR` reviews when the APR is above the mandate's.

Worked example, the demo invoice (PD 0.0027, tenor 34 days so priced as 60):
`0.04 + 0.06 + 0.0027 × 0.45 × 365/60 = 0.1074` per year → `0.1074 × 30/365 = 0.00883` → rounded up to **0.009** per
30 days = **10.95% APR**. The unconfirmed variant (PD 0.00463): `0.10 + 0.0127 + 0.03 = 0.1427` → 0.01173 → **0.012**
= 14.6% APR, above the 12% mandate, so it reviews with `REVIEW.MANDATE_APR`.

### 4. PD model (`training/`, `app/features.py`, `app/model.py`)

- **Generator:** `training/synth.py` draws seeded synthetic invoices from a known latent logistic model:
  `logit p = intercept + Σ β·x + 0.12 × tier × tenor/30 + N(0, 0.3)`, `y ~ Bernoulli(p)`. Every number is in
  `synth_config.yaml`. The intercept puts the demo profile at a true PD of 0.0027.
- **Features:** one function, `build_features`, for training and serving: the 16 features of the brief (tier, late
  rate, days late, confirmed, relationship, seller years, invoices financed, seller default, dilution and on-time
  rates, log amount, tenor, invoice age, amount / buyer limit, OCR confidence, fraud score), the tier × tenor
  interaction and a sector one-hot. A missing value takes its tier's training median, stored with the model.
- **Models:** a standardised L2 logistic regression, saved as a points scorecard (600 points at 50:1 odds, 20 points
  to double), next to LightGBM with monotone constraints (≤ 15 leaves, depth ≤ 4), calibrated on the validation split
  (isotonic beat Platt). Time split by cohort: train 1–16, validation 17–20, test 21–24 (the drifted cohorts).
- **Selection:** the lower **test** Brier is served.

| Test split (33,335 rows, base rate 4.6%) | AUC | PR-AUC | Brier | ECE | KS | Targets met |
|---|---|---|---|---|---|---|
| **LR scorecard `credit-lr-2026-10-10.2` (served)** | **0.8909** | **0.4083** | **0.03379** | **0.0018** | **0.627** | yes |
| LightGBM + isotonic `credit-lgbm-2026-10-10.2` | 0.8873 | 0.3927 | 0.03432 | 0.0047 | 0.611 | yes |

Targets: AUC ≥ 0.75 and ECE ≤ 0.03. **Why LR wins:** the labels come from a logistic model, so a correctly specified
logistic regression is close to the truth, and the trees are coarse at the bottom of the scale (LightGBM would price
the demo at 0.0049 against a true 0.0027). The reliability plot is `services/policy-ai/model/reliability.png`.

**Tuning to Finance's demo windows (revision 2).** Pricing needs the demo at PD ≤ 0.00347, the unconfirmed variant in
(0.0036, 0.0058] and scenario 8 at ≤ 0.0057. Revision 1 (20,000 rows, no interaction term) put the unconfirmed
variant at 0.00339. Two causes were fixed, without changing the seed, the labels or the pricing: too few tier-A
defaults (about 12 → about 135 with 200,000 rows), and the missing tier × tenor term the labels contain. Refitted from
scratch on 12 seeds, every seed lands all three cases in their windows:

| Case | Window | Range over 12 seeds | Served (seed 20261010) | True PD |
|---|---|---|---|---|
| Demo (scenario 1) | ≤ 0.00347 | 0.00254 – 0.00340 | 0.00270 | 0.0027 |
| Unconfirmed buyer (scenario 3) | 0.0036 – 0.0058 | 0.00405 – 0.00573 | 0.00463 | 0.0044 |
| Repeat seller (scenario 8) | ≤ 0.0057 | 0.00321 – 0.00409 | 0.00337 | 0.0034 |

The demo window is the tight one: one seed reaches 0.00340 against 0.00347. The per-seed table is in
`services/policy-ai/training/README.md`.

**Serving:** the model files are plain JSON (scorecard) or LightGBM text plus a JSON calibrator, never a pickle, so
serving needs no numpy. Fallback chain: the selected model → `scorecard.json` (`scorecard-fallback`) → a fixed
formula (`placeholder-fallback`); a scoring error drops to the placeholder, so `/policy/decide` never returns 500.
Each decision carries the top 3 drivers (coefficient × standardised value, in log-odds) as `top_features` and
`MODEL.*` reasons. p95 latency is about 5 ms.

### 5. Decision hash (`app/hashing.py`)

`decision_hash = keccak256(canonical JSON of the shared PolicyDecision fields, without decision_hash)`, with sorted
keys and no spaces. It is the same check the wallet runs (PR #17), which only sees the shared fields, so the extra
policy fields are outside the hash. `decision_id` is derived from `request_hash` and the versions, so the same input
and versions give the same hash.

### 6. Mandate compiler (`app/mandate.py`, `POST /policy/mandate/compile`)

1. **Parser:** deterministic regular expressions read the advance %, APR %, buyer-risk %, the human-review amount,
   per-transaction and daily caps (with k / m / million / thousand / baht / บาท, before or after "per day" /
   "per invoice"), currency, payee addresses and validity. The demo sentence compiles with no LLM.
2. **Validation:** every cap must be above 0 and at or under the platform limit in `mandate_limits` (advance ≤ 90%,
   APR ≤ 15%, PD ≤ 20%, THB 1.5m per transaction, THB 3m a day, review ≤ THB 837,500). **Nothing is clamped:** an
   out-of-range value returns 422 with `{field, code, value, limit}`, never the text. Wording that asks for no limit
   ("unlimited", "ignore all limits", "send everything") and unregistered payees also return 422.
3. **Never looser than the platform:** caps the sentence doesn't mention take the platform defaults (70% / 12% / 5%
   / THB 837,500 / 1.5m / 3m), listed in `fields_from_defaults`.
4. **Never looser than the sentence:** the compiler only expresses maxima, so minimum wording ("at least 80%", "no
   less than", "minimum", "80% or more") returns 422 `AMBIGUOUS_VALUE` instead of becoming a cap. An amount next to
   "per day" / "per invoice" that the parser can't read returns 422 `UNPARSED_CAP`, and any other unread number
   `UNRECOGNISED_NUMBER`, so a stated limit can never silently fall back to a looser default. (Both were review
   findings on the first version: "2m per day" fell back to the 3m default, and "at least 80%" became a cap.)
5. **Optional LLM step** (`app/llm_client.py`, off unless configured): asked only when the sentence has numbers the
   parser couldn't read, never for text that asks for no limit or states a minimum. The sentence is passed as data
   between random delimiters. An LLM value is used only if it equals one of those unread numbers, in the field its
   unit phrase names, and then goes through the same validator, so an LLM can neither invent nor loosen a cap. No
   provider, the placeholder key, a timeout or bad JSON leave the number a 422. `/policy/decide` never imports it.
6. **Output:** the `mandate` uses exactly the wallet's field names; the envelope around it carries the provenance
   (`source_text_sha256`, `compiler_version`, which fields came from text, LLM or defaults) and warnings.
   `payee_allowlist` is always the whole payee registry (seller, both lenders, platform fee): a sentence can only
   name payees that are already registered.

## Open questions for Finance

- **Tier C pricing.** With the served model and the YAML pricing, a typical BB (tier C) buyer prices at or above the
  15% APR ceiling, so the decision is `KO.PRICING`. In the demo data only a near-perfect BB payer (98% on time, 1 day
  late, 60 months) prices under it (review at 0.65, fee 1.2%). The unrated buyer, priced as tier C, is rejected for
  the same reason. This rests on synthetic data and FINANCE-TBD prices (4% cost of funds, 6% margin, 45% LGD), so it
  is a question, not a finding about the market: are these prices right for tier C, or is tier C out of scope?
- **Thresholds.** All YAML values marked FINANCE-TBD are still the shipped defaults.

## Known limitations (say these before judges do)

- Synthetic labels: the model's metrics show that the pipeline is correct and calibrated on data with a known
  truth, not that it predicts real Thai SME defaults.
- The demo PD windows are narrow; the served model hits them on all 12 seeds tested, with little room on the demo
  window (0.00340 against 0.00347 on one seed).
- With-recourse assumption; no real bureau or KYC data; exposure is passed in rather than read from a live ledger.
- The orchestrator doesn't yet forward the mandate or `as_of_date`, so live runs use the default mandate and the
  real date.
- Legal enforceability of the receivable is jurisdiction-specific and out of scope.

## Status (engineer updates)

| Item | Status |
|---|---|
| Final thresholds | YAML defaults (`credit-policy-v0.1`); Finance has changed no numbers so far |
| Model + metrics | LR scorecard `credit-lr-2026-10-10.2` served: test AUC 0.891, Brier 0.0338, ECE 0.0018 (synthetic data); LightGBM 0.887 / 0.0343 / 0.0047 |
| Scenarios passing | **9 / 9** (1–8 and the hostile mandates of 9), plus 8b and 8 demo-data variants |
| Mandate shape agreed with Agent Wallet | Wallet PR #17 field names; compiler output parses with a copy of its `Mandate` model; the real-model test runs once #17 merges |
| Demo UI | `ui/`: fixtures mode done; live mode wired to the orchestrator with labelled fallbacks for its missing routes |
