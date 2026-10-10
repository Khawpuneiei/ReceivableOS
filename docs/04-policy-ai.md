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
| Mandate field names | `max_ltv`, `max_apr`, `max_predicted_default`, `human_review_above`… (from your architecture doc) | Proposal; will match whatever the Agent Wallet guard consumes. |

## How a decision is made

1. **Hard rules (team-wide):** fraud score ≥ 0.30 ⇒ reject; any injection flag ⇒ review; OCR confidence < 0.80 ⇒ review.
2. **Knock-outs ⇒ reject:** duplicate invoice, invoice vs PO mismatch > 5% (OCR flag), KYC expired, overdue,
   < 7 or > 120 days to due, older than 90 days, buyer tier D, unsupported currency, no facility headroom,
   price above the 15% APR legal ceiling.
3. **Credit model ⇒ PD:** PD > 15% rejects; PD above the mandate's max (5%) sends to review.
4. **Review triggers:** buyer hasn't confirmed, other fraud flags, line items don't sum (± 7% VAT), new seller,
   above the human-review amount (THB 837,500), concentration > 30% of the pool, no buyer rating, price above the
   mandate APR.
5. **Terms:** base advance by buyer tier (A 80%, B 75%, C 65%) minus haircuts (unconfirmed −20 pts, long tenor,
   old invoice, high dilution, PD > 3%), floor 50%, capped by the mandate and facility limits.
6. **Price:** `annual = 4% cost of funds + 6% margin + PD × 45% LGD × 365/max(tenor, 60) [+3% if unconfirmed]`,
   converted to per 30 days and rounded up to 0.05% steps.

All thresholds are YAML defaults marked **FINANCE-TBD**; Finance's Oct 11 sign-offs change YAML only, not code.

## The shared demo, reproduced

Siam Fresh Pack → Mekong Basket Retail, THB 749,000, tenor 34 days, buyer A- and confirmed, mandate 70% / 12% APR / 5%:
advance 0.80 capped to **0.70**, limit **"524300.00"**, PD ≈ 0.3%, fee **0.009** per 30 days (10.95% APR) ⇒ **approve**.
Unconfirmed-buyer variant ⇒ **review**, 0.60, 0.012 — both match Finance's expected numbers (except `risk_score`, above).

Test scenarios: happy path, inflated amount (reject), unconfirmed buyer (review), injected text (review, never
100% advance), duplicate (reject), high fraud score (reject), expired KYC (reject), repeat seller after late and
partial payment (smaller advance), hostile mandate text (no looser caps). Expensive-lender and over-LTV offers are
blocked by the wallet guard, not here.

## Demo UI and demo data (also owned by the Policy AI engineer)

- **UI:** one Streamlit screen in `ui/` on port 3000, talking only to the orchestrator: mandate → invoice evidence →
  decision with reasons and PD gauge → lender offers → on-chain tx timeline → attack buttons A1–A6, each adding a red
  BLOCKED row with who stopped it and the tx hash. Runs from saved fixtures until the orchestrator is ready. You wire
  it to the orchestrator. Built only after the credit decision passes its scenarios. Layout in CLAUDE.md §12.
- **Demo data:** 5 sellers, 5 buyers, 3 mandates and one request + expected result per scenario, matching
  Finance's numbers and OCR's sample invoices (checksum-valid tax IDs 0105559000000 / 0107559000001,
  buyer "Mekong Basket Retail PCL"). You recheck.
- **Pitch pack:** the engineer supplies the "how the AI decides" slides (pipeline, rules as data, calibration plot,
  mandate JSON, blocked-attack screenshot).

## Credit risk model

- **Target:** buyer doesn't pay within 60 days after the due date.
- **Features:** buyer tier, lateness, on-time rate, confirmation, relationship length; seller age, financing history,
  default, dilution and on-time rates; amount, tenor, invoice age, amount vs buyer limit, OCR confidence, fraud score, sector.
- **Data:** 20k synthetic THB invoices from a known latent model (≈ 4% base default, 24 monthly cohorts, drift in
  the last 6). Openly synthetic; the claim is a correct, calibrated pipeline. Finance's feature ranges (Oct 11) tune it.
- **Models:** logistic-regression scorecard (baseline, judge-friendly points) next to calibrated LightGBM with
  monotone constraints; serve the better Brier score.
- **Targets on the time-split test set:** AUC ≥ 0.75, ECE ≤ 0.03, AUC and Brier reported for both models.
- **Why calibration matters:** PD sets haircuts, price and the review gate, so "0.3%" must mean about 0.3%.

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

## Known limitations (say these before judges do)

Synthetic labels; with-recourse assumption; no real bureau or KYC data; exposure is passed in rather than read from
a live ledger; legal enforceability of the receivable is jurisdiction-specific and out of scope.

## Status (engineer updates)

| Item | Status |
|---|---|
| Final thresholds | _YAML defaults, pending Finance sign-off_ |
| Model + metrics | _not trained yet_ |
| Scenarios passing | _0 / 9_ |
| Mandate shape agreed with Agent Wallet | _pending_ |
