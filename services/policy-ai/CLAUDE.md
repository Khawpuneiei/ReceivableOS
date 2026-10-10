# Policy AI service — build brief for AI coding assistants

> Paste this file (or point your assistant at it) before you start coding in `services/policy-ai/`.
> Read the root `CLAUDE.md` (team rules) and `shared/schemas.py` (the contract) first; this file adds what is
> specific to Policy AI: scope, design, rule set, credit model, mandate compiler, build plan, acceptance criteria
> and ready-to-paste prompts.
> Owner: Policy AI engineer. Reviewer: P (PM). Deadline: end of **Oct 12** (Bangkok time).

---

## 1. Context in 60 seconds

**ReceivableOS** is our FinTechathon 2026 entry (Agent Wallet track). An SME uploads an invoice; the system
verifies it, scores it, decides whether and how much to finance, and the **Agent Wallet** executes the financing
on-chain (FISCO BCOS, `LEDGER_MODE=mock` by default) — but only inside limits that deterministic code enforces.

```
invoice file ──► ocr-ai :8001 ──► policy-ai :8002 ──► agent-wallet :8003 ──► FISCO BCOS / mock ledger
                 extract,         THIS SERVICE:        guard + execute
                 injection,       credit decision      within the mandate
                 fraud score      + mandate compiler
```

Judging weights: task completion 40%, **security/compliance 30%**, innovation/interaction 30%.

"Policy" means two things in this project. You own the first and the **schema + compiler** of the second:

| | Credit policy (you own fully) | Mandate / guard policy (you compile, Agent eng enforces) |
|---|---|---|
| Question | Should we finance this invoice, how much, at what price? | What may the wallet do at all? |
| Input | invoice + supplier/buyer profiles | the SME's plain-language instruction |
| Output | `decision, advance_rate, limit, fee_rate, risk_score, reasons` | mandate JSON (max advance, max APR, max PD, caps, payees, expiry) |
| Endpoint | `POST /policy/decide` | `POST /policy/mandate/compile` |

**Core principle (do not break this):**

> **An LLM never decides money.** Credit terms come only from a versioned YAML rule set evaluated by deterministic
> code, plus a calibrated ML probability. In the mandate compiler the LLM only *proposes* JSON; a schema + range
> validator decides what becomes the mandate. An LLM never sees raw invoice text from this service.

---

## 2. Goal

Replace the stub in `services/policy-ai/app/main.py` with a service that returns an **explainable, reproducible
financing decision** and compiles plain-language mandates into **validated JSON**:

- `approve` with terms, `review` (a human must look), or `reject`;
- a calibrated **probability of default** (`risk_score`) from a small credit model trained on synthetic data;
- `reasons` that cite exact rule IDs and the top model drivers;
- a `decision_hash` the Agent Wallet can commit on-chain as the audit reference;
- a mandate JSON the wallet's guard enforces.

## 3. Scope

**Must ship:**
1. `POST /policy/decide` matching `shared/schemas.py` (`PolicyRequest` → `PolicyDecision`), plus optional additive fields.
2. YAML rule set + small rule engine: hard rules, knock-outs, review triggers, terms, pricing, concentration.
3. Synthetic data generator + credit risk model (logistic-regression scorecard as baseline, LightGBM as main),
   calibration, explanations, metrics report (AUC + Brier next to the baseline).
4. `POST /policy/mandate/compile`: plain language → validated mandate JSON, works **without an LLM** via a
   deterministic parser for the demo sentence; rejects out-of-range values with an error.
5. Fixtures for the demo scenarios (§10) and tests for every rule that rejects or reviews.
6. `GET /health` (keep it), `GET /policy/rules` (active rule set + version, for the dashboard).

**Stretch (only after must-ship is green):**
- `POST /policy/explain` — LLM narrative of a finished decision (decision JSON in, ≤ 80 words out, numbers checked).
- `POST /policy/simulate` — what-if: change one input, show how the terms move.

**Out of scope (do not build):** OCR, fraud models, document injection detection (OCR AI owns these; you only
*consume* `fraud_score`, `fraud_flags`, `injection_flags`, `confidence`), duplicate-invoice registry (orchestrator /
chain), wallet, signing, guard enforcement, contracts (Agent AI eng), lender quotes and KYC mock (orchestrator, PM),
frontend, real bureau/KYC data, TabPFN / GNN / federated learning (roadmap slide only).
**Do not edit `shared/schemas.py`** — contract changes are a separate `contract:` PR by/with P.

---

## 4. Domain primer

| Term | Meaning in ReceivableOS |
|---|---|
| Supplier / Seller | The SME that issued the invoice and wants cash now. |
| Buyer / Debtor / Obligor | The company that owes the invoice. **Its** credit quality drives most of the risk. |
| Face value | `invoice.amount`. |
| Advance rate (≈ LTV) | Fraction of face value paid out now (0.70 → THB 524,300 on 749,000). The rest buffers dilution and loss. |
| Limit | The cash amount we are willing to advance after every cap. `advance_rate × amount = limit`. |
| Fee rate | Discount fee **per 30 days** on the advance (Thai factoring convention, `docs/02-finance-domain.md`): 0.009 = 0.90% per 30 days ≈ 10.95% APR. Policy returns the **risk-based maximum** fee; the wallet accepts a lender quote only if quote ≤ `fee_rate` and quote × 365/30 ≤ `mandate.max_apr`. |
| APR | `fee_rate × 365 / 30` (simple). Used for mandate caps ("APR ≤ 12%"). |
| Tenor | Days from the decision date to `due_date`. |
| Invoice age | Days from `issue_date` to the decision date. Old invoices are riskier. |
| PD | Probability the buyer does **not** pay within 60 days after the due date (invoice-level). |
| LGD | Share of the advance lost on default. Default 0.45 (FINANCE-TBD). |
| Buyer confirmation | Buyer signed an acceptance of the invoice. Strongest single evidence; without it advance drops and the case goes to review. |
| Expected loss (EL) | `PD × LGD × limit`. |
| Concentration | Share of the pool exposed to one buyer or supplier; capped. |
| Dilution | Value lost to credit notes, returns, rebates, disputes (common with retail buyers). Seller's historical `dilution_rate` is a feature and a haircut. |
| Recourse | MVP assumes **with recourse** (supplier repays if buyer doesn't). Say so in the pitch. |

---

## 5. API

### 5.1 The contract you must keep (`shared/schemas.py`, owned by P)

```python
class PolicyRequest(BaseModel):           # body of POST /policy/decide
    invoice: ExtractedInvoice             # OCR output: invoice_id, supplier (str), buyer (str), invoice_no,
                                          # issue_date, due_date, amount (Decimal), currency, line_items,
                                          # confidence, injection_flags, fraud_score, fraud_flags
    supplier_profile: dict[str, Any] = {}
    buyer_profile: dict[str, Any] = {}

class PolicyDecision(BaseModel):          # response
    decision: Decision                    # approve | review | reject
    advance_rate: float                   # 0..1
    limit: Decimal                        # serialises as a decimal string, e.g. "7000.00"
    fee_rate: float                       # per 30 days on the advance (0.009 = 0.90%/30d)
    risk_score: float                     # 0..1, higher = riskier; WE DEFINE IT as the calibrated PD over the tenor
    reasons: list[str]
```

Money is Decimal (string in JSON), rates and scores are floats, dates ISO. Import these models — don't copy them.

### 5.2 What you add inside your service (allowed: optional fields only)

In `app/schemas.py` define **subclasses**, never edits:

```python
class PolicyRequestExt(PolicyRequest):
    portfolio: Portfolio | None = None     # {total_exposure: Decimal, pool_capacity: Decimal}; defaults from YAML
    mandate: Mandate | None = None         # §7 shape; orchestrator passes the active mandate if it has one
    as_of_date: date | None = None         # defaults to today; makes tests/hashes reproducible

class PolicyDecisionExt(PolicyDecision):
    model_version: str                     # e.g. "credit-lgbm-2026-10-11.1"
    policy_version: str                    # e.g. "credit-policy-v0.1"
    decision_id: str
    pd: float                              # = risk_score
    expected_loss: Decimal
    tenor_days: int
    apr: float                             # fee_rate × 365/30
    fee_amount: Decimal                    # limit × fee_rate × tenor_days/30
    reason_details: list[ReasonDetail]     # {code, source: rule|model, message, effect}
    top_features: list[FeatureContribution]  # {feature, value, contribution}
    rule_trace: list[str]                  # "KO.FRAUD_SCORE:pass", "REVIEW.CONFIDENCE:hit", "REVIEW.NEW_SUPPLIER:skip(missing)"
    valid_until: datetime                  # wall clock now + decision_ttl_hours; wallet must not execute after it
    decision_hash: str                     # "0x" + sha256, see below
```

`reasons` (contract) stays a list of **strings**, each prefixed with the rule code so it is human- and
machine-readable: `"TERMS.MANDATE_CAP: advance capped at 70% by mandate"`. `reason_details` carries the structure.

**`risk_score` = calibrated PD.** Finance's primer describes it as "combined fraud + credit risk" and shows 0.18
for the happy path. We use the calibrated PD over the tenor instead (≈ 0.003 for the happy path) because the
mandate caps `max_predicted_default` at 0.05 and the wallet compares against it; a composite score would trip that
cap and is not a probability. Fraud stays visible as `invoice.fraud_score` and in the reasons. (Flagged to P and
Finance; if P decides otherwise, add a separate `pd` and redefine only `risk_score`.)

**Response rules**
- `reject` ⇒ `advance_rate = 0`, `limit = "0.00"`, `fee_rate = 0`; at least one `HARD.*` or `KO.*` reason.
- `review` ⇒ terms filled with what **would** apply if a human approves; at least one `HARD.*`/`REVIEW.*` reason.
  The wallet treats `review` as "needs human approval".
- `approve` ⇒ no `KO.*`/`REVIEW.*` hits.
- `decision_hash = "0x" + sha256(canonical_json({request, decision_fields, policy_version, model_version}))`,
  canonical JSON = `json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)`, where `decision_fields`
  excludes `decision_id`, `valid_until` and `decision_hash`. Same input + same versions ⇒ same hash.

### 5.3 Profiles are free-form dicts — normalise them

`supplier_profile` and `buyer_profile` are `dict[str, Any]` in the contract, and `integration/samples/profiles.json`
currently sends only a few keys. Write `app/profiles.py` that converts each dict into a typed internal model, with
**aliases** and **explicit "missing" handling**:

| Internal field | Accepted keys (first found wins) | If missing |
|---|---|---|
| `supplier.years_in_business` | `years_in_business`, `years_trading` | skip rules that need it |
| `supplier.invoices_financed_count` | `invoices_financed_count` | skip `REVIEW.NEW_SUPPLIER` |
| `supplier.historical_default_rate` | `historical_default_rate` | model uses tier median |
| `supplier.dilution_rate` | `dilution_rate`, `dispute_rate` | model uses median; haircut skipped |
| `supplier.on_time_ratio` | `on_time_ratio`, else `paid_on_time / invoices_total` | model uses median |
| `supplier.kyc_valid`, `supplier.kyc_expiry` | same | `kyc_valid` missing ⇒ `HARD.KYC_UNKNOWN` → review |
| `supplier.current_exposure`, `supplier.facility_limit` | same (`supplier_limit` accepted) | 0 / no cap |
| `buyer.credit_tier` (A–D) | `credit_tier`, else map `credit_rating` / `internal_rating`: AAA–A- → A, BBB± → B, BB± → C, B+ and below → D | tier C + `REVIEW.THIN_PROFILE` |
| `buyer.late_payment_rate` | `late_payment_rate`, else `1 − on_time_payment_rate` | tier median |
| `buyer.avg_days_late` | `avg_days_late` | tier median |
| `buyer.confirmed` | `buyer_confirmed`, `buyer_acknowledged` | `false` ⇒ haircut + `REVIEW.UNCONFIRMED_BUYER` |
| `buyer.relationship_months` | `relationship_months` | 0 |
| `buyer.current_exposure`, `buyer.buyer_limit` | same | 0 / no cap |
| `buyer.sector` | `sector` | `"other"` |

Rules whose inputs are missing are **skipped and logged** in `rule_trace` as `skip(missing)`, never silently
evaluated on a guessed value. Send P the full profile shape (§5.4 example) so `integration/samples/profiles.json`
can be extended — that file is the PM's, don't edit it yourself.

Example of a full profile pair — the shared demo scenario from `docs/02-finance-domain.md` §10 (use for fixtures):

```json
{
  "supplier_profile": {
    "name": "Siam Fresh Pack Co., Ltd.", "tax_id": "0105559000001", "wallet_address": "0xSUPPLIER",
    "years_trading": 3, "revenue_thb": "62000000.00", "invoices_financed_count": 12,
    "invoices_total": 36, "paid_on_time": 34, "historical_default_rate": 0.0, "dilution_rate": 0.02,
    "kyc_valid": true, "kyc_expiry": "2027-06-30",
    "current_exposure": "0.00", "facility_limit": "3000000.00"
  },
  "buyer_profile": {
    "name": "Mekong Basket Retail PCL", "tax_id": "0107559000002", "internal_rating": "A-",
    "revenue_thb": "18000000000.00", "on_time_payment_rate": 0.97, "avg_days_late": 1.5,
    "buyer_confirmed": true, "relationship_months": 36, "sector": "retail",
    "current_exposure": "0.00", "buyer_limit": "10000000.00"
  }
}
```

`invoices_financed_count`, `on_time_payment_rate`, `avg_days_late`, `dilution_rate` and `buyer_limit` are our
estimates, not in Finance's primer; ask Finance to confirm them at their Oct 11 sign-off.

### 5.4 Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Keep the stub's shape; add `policy_version`, `model_version`. |
| POST | `/policy/decide` | Credit decision (§6, §8). |
| POST | `/policy/mandate/compile` | `{"text": "...", "mandate_id"?: "..."}` → mandate JSON (§7) or HTTP 422 `{"detail": [violations]}`. |
| GET | `/policy/rules` | Active YAML as JSON (dashboard: "the rules the AI must obey"). |
| POST | `/policy/explain` (stretch) | Decision JSON → `{"explanation": "..."}`. |

### 5.5 Interfaces with other modules

| Counterpart | You need | They need from you | Stand-in until it arrives |
|---|---|---|---|
| **OCR AI** | `ExtractedInvoice`, especially `amount`, dates, `confidence`, `fraud_score`, `fraud_flags`, `injection_flags` | The exact flag strings you key on: `duplicate_invoice_hash` (KO). Any non-empty `injection_flags` ⇒ review. | Hand-written fixtures; the OCR stub. |
| **Finance** | Advance rates by tier, fee range, LGD, tenor/age limits, concentration caps, typical SME default/late rates for the synthetic data | The YAML + `training/synth_config.yaml` to sanity-check | Defaults marked `FINANCE-TBD` (YAML-only edits later). |
| **Agent Wallet** | The JSON mandate shape its guard consumes (coordinator relays it; adopt their field names) | `decision`, `limit`, `fee_rate`, `risk_score`, `decision_hash`, `valid_until`, `policy_version`; mandate JSON | Mandate shape in §7. |
| **Orchestrator (PM)** | Supplier/buyer profiles (not produced by OCR); the active mandate (optional) | Profile shape (§5.3); `reasons`, `rule_trace`, `top_features`, `/policy/rules` for the UI | Fixture profiles. |

---

## 6. Credit policy design (rules as data)

Rules live in `services/policy-ai/rules/policy.v1.yaml`, are validated at startup, and evaluated in a fixed order.
Every rule has an `id`, a human `message` and parameters. Changing a number = editing YAML + bumping `version`.
**No threshold is hard-coded in Python.**

### 6.1 Evaluation order

```
1. Normalise profiles, derive features (tenor_days, invoice_age_days, line_items_sum, shares after financing)
2. Hard rules (team-wide, from docs/00-scope.md §4.2) — applied before any model:
     fraud_score ≥ 0.30            ⇒ reject  (HARD.FRAUD_SCORE)
     injection_flags non-empty     ⇒ review  (HARD.INJECTION)
     confidence < 0.80             ⇒ review  (HARD.LOW_CONFIDENCE)
3. Knock-outs (KO) ⇒ reject; collect ALL hits, don't stop at the first
4. Model: PD = calibrated model(features)
5. PD gates: PD > reject_above ⇒ reject (KO.PD_TOO_HIGH); PD > min(review_above, mandate.max_predicted_default) ⇒ review
6. Review triggers ⇒ review (terms still computed)
7. Terms: base advance by tier → haircuts → floor → mandate cap → exposure/concentration caps → limit
8. Pricing (annual first, then per 30 days):
           annual = cost_of_funds + margin + PD×LGD×365/max(tenor, min_pricing_tenor) [+ unconfirmed_premium]
           fee_rate = ceil_to_step(annual × 30/365, 0.0005), clamped to [min_fee_rate, max_fee_rate]
           APR > platform max_apr (15%, Thai legal ceiling) ⇒ reject (KO.PRICING)
           APR > mandate.max_apr ⇒ review (REVIEW.MANDATE_APR)
9. Package: reasons, reason_details, rule_trace, versions, valid_until, decision_hash
```

The final decision is the most severe outcome hit: reject > review > approve.

### 6.2 Starter rule set (`FINANCE-TBD` = Finance confirms the number)

```yaml
version: credit-policy-v0.1
currency_allowlist: [THB, USD]
lgd: 0.45                              # FINANCE-TBD
decision_ttl_hours: 24
defaults:
  pool_capacity: {THB: "100000000.00", USD: "3000000.00"}
  max_pd: 0.05                         # used when no mandate is passed
  human_review_above: {THB: "837500.00", USD: "25000.00"}   # mandate value wins when passed

hard_rules:                            # team-wide (docs/00-scope.md §4.2); change only with P
  - {id: HARD.FRAUD_SCORE,    outcome: reject, param: {min_fraud_score: 0.30}}
  - {id: HARD.INJECTION,      outcome: review}
  - {id: HARD.LOW_CONFIDENCE, outcome: review, param: {min_confidence: 0.80}}
  - {id: HARD.KYC_UNKNOWN,    outcome: review}

knockouts:                             # outcome: reject
  - {id: KO.DUPLICATE,        param: {flags: [duplicate_invoice_hash, duplicate_fingerprint]}, message: "Invoice already registered or financed"}
  - {id: KO.PO_MISMATCH,      param: {flags: [po_amount_mismatch]}, message: "Invoice amount differs from PO by more than 5%"}  # OCR raises the flag
  - {id: KO.KYC_INVALID,      message: "Seller KYC invalid or expired"}
  - {id: KO.OVERDUE,          message: "Invoice already past due"}
  - {id: KO.TENOR_TOO_SHORT,  param: {min_tenor_days: 7},   message: "Less than 7 days to due date"}
  - {id: KO.TENOR_TOO_LONG,   param: {max_tenor_days: 120}, message: "Tenor beyond 120 days"}
  - {id: KO.TOO_OLD,          param: {max_age_days: 90},    message: "Invoice older than 90 days"}   # FINANCE-TBD
  - {id: KO.BUYER_TIER,       param: {ineligible: [D]},     message: "Buyer credit tier not eligible"}
  - {id: KO.CURRENCY,         message: "Currency not supported"}
  - {id: KO.DATES_INVALID,    message: "Due date before issue date"}
  - {id: KO.NO_HEADROOM,      message: "No remaining facility for buyer or seller"}
  - {id: KO.PRICING,          param: {max_apr: 0.15}, message: "Risk price above 15% APR legal ceiling"}

pd_gates:
  reject_above: 0.15                   # FINANCE-TBD
  review_above: 0.05                   # mandate max_predicted_default wins if lower

review_triggers:                       # outcome: review
  - {id: REVIEW.UNCONFIRMED_BUYER,    message: "Buyer has not confirmed the invoice"}
  - {id: REVIEW.FRAUD_FLAGS,          message: "OCR raised fraud flags"}   # any flag not handled by a KO
  - {id: REVIEW.LINE_ITEMS_MISMATCH,  param: {tolerance: 0.01, vat_rates: [0.0, 0.07]}, message: "Line items (± VAT) don't sum to the total"}
  - {id: REVIEW.NEW_SUPPLIER,         param: {min_financed: 3}, message: "Fewer than 3 invoices financed before"}
  - {id: REVIEW.LARGE_TICKET,         message: "Above the human-review amount"}
  - {id: REVIEW.CONCENTRATION,        param: {max_buyer_share: 0.30, max_supplier_share: 0.30}}
  - {id: REVIEW.THIN_PROFILE,         message: "Buyer has no tier or rating"}
  - {id: REVIEW.MANDATE_APR,          message: "Risk price above the seller's APR mandate"}

terms:
  base_advance_by_tier: {A: 0.80, B: 0.75, C: 0.65}   # FINANCE-TBD (primer: 80–90% strong confirmed, 60–75% weaker)
  haircuts:
    - {id: TERMS.HAIRCUT_UNCONFIRMED,                         minus: 0.20}
    - {id: TERMS.HAIRCUT_TENOR,    param: {tenor_above: 90},   minus: 0.05}
    - {id: TERMS.HAIRCUT_AGE,      param: {age_above: 60},     minus: 0.05}
    - {id: TERMS.HAIRCUT_DILUTION, param: {dilution_above: 0.05}, minus: 0.05}
    - {id: TERMS.HAIRCUT_PD,       param: {pd_above: 0.03},    minus: 0.05}
  floor_advance: 0.50
  max_single_invoice_limit: {THB: "3000000.00", USD: "90000.00"}

pricing:
  cost_of_funds: 0.04                  # annual, FINANCE-TBD (primer §10 uses 4%)
  margin: 0.06                         # annual lender margin, FINANCE-TBD
  unconfirmed_premium: 0.03            # annual, added when the buyer hasn't confirmed
  min_pricing_tenor_days: 60           # short invoices priced as 60 days for the EL premium
  fee_step: 0.0005                     # quotes move in 0.05% steps; round UP
  min_fee_rate: 0.005                  # per 30 days
  max_fee_rate: 0.0123                 # per 30 days (= 15% APR)

mandate_limits:                        # platform maxima for the mandate compiler (§7)
  max_ltv: 0.90
  max_apr: 0.15
  max_predicted_default: 0.20
  defaults: {max_ltv: 0.70, max_apr: 0.12, max_predicted_default: 0.05}
```

**Terms algorithm (deterministic, use `Decimal` for money):**
```
advance = base_advance_by_tier[tier] − Σ triggered haircuts
advance = max(advance, floor_advance)
advance = min(advance, mandate.max_ltv)                       if a mandate is passed
limit   = advance × amount
limit   = min(limit,
              buyer_limit − buyer.current_exposure,          (if buyer_limit known)
              facility_limit − supplier.current_exposure,    (if known)
              max_single_invoice_limit[currency])
limit <= 0 ⇒ KO.NO_HEADROOM
advance_rate (reported) = round(limit / amount, 4)            so advance_rate × amount == limit
money → 2 dp (ROUND_DOWN for limit), rates → 4 dp
```
Every step that changes a number appends a reason with its rule `id`.

**Worked example — the shared demo** (`docs/02-finance-domain.md` §10): Siam Fresh Pack invoices Mekong Basket
Retail THB 749,000.00, issued 2026-10-01, due 2026-11-15, financed 2026-10-12 (tenor 34 days); buyer rated A- ⇒
tier A, buyer confirmed; mandate max_ltv 0.70, max_apr 0.12, max_predicted_default 0.05.

```
advance  = 0.80 (tier A) → no haircuts → mandate cap 0.70           ⇒ advance_rate 0.70
limit    = 749,000 × 0.70 = 524,300.00 (under facility 3,000,000)    ⇒ limit "524300.00"
PD       ≈ 0.003 over the tenor                                       ⇒ risk_score ≈ 0.003, no PD haircut
annual   = 0.04 + 0.06 + 0.003 × 0.45 × 365/60 ≈ 0.1082
fee_rate = ceil(0.1082 × 30/365 = 0.00889, step 0.0005)               ⇒ fee_rate 0.009 (APR 10.95% ≤ 12%)
fee      = 524,300 × 0.009 × 34/30 = 5,347.86                         ⇒ decision approve
```

This reproduces Finance's expected output (advance 0.70, limit "524300.00", fee_rate 0.009) except `risk_score`,
which we define as PD (see §5.2). Lender A (0.90%/30d) and Lender B (0.75%/30d) both pass; a 1.6%/30d quote
(≈ 19.5% APR) is the wallet guard's job to revert. Without a mandate the same invoice gets advance 0.80.

Unconfirmed buyer (Finance variant V3): 0.80 − 0.20 = **0.60**; PD ≈ 0.005; annual ≈ 0.04 + 0.06 + 0.03 + 0.0133
≈ 0.143 → fee_rate **0.012** (APR 14.6%) ⇒ **review** (`REVIEW.UNCONFIRMED_BUYER`, `REVIEW.MANDATE_APR`).
That matches Finance's V3 expectation (review, 0.60, 0.012).

### 6.3 Evaluating rules safely

**Do not `eval` YAML strings.** Implement each rule as a small Python predicate registered by `id`
(`RULES: dict[str, Callable[[Ctx, dict], RuleResult]]`) and keep only the *parameters* in YAML. Startup must fail
if the YAML names an `id` with no predicate, or a predicate has no YAML entry.

---

## 7. Mandate compiler (plain language → validated JSON)

The SME types (THB version of the demo): *"Finance my approved invoices automatically, but never advance more
than 70%, never pay more than 12% APR, stop if buyer risk is above 5%, and ask me above THB 837,500."*
The compiler shows this JSON (field names from P's architecture doc, as Finance's primer also uses):

```json
{
  "mandate_id": "m_sfp_001",
  "version": "mandate-v0.1",
  "asset_type": "trade_receivable",
  "max_ltv": 0.70,
  "max_apr": 0.12,
  "max_predicted_default": 0.05,
  "human_review_above": "837500.00",
  "currency": "THB",
  "allowed_settlement_asset": "tTHB",
  "allowed_payees": ["0xSUPPLIER"],
  "require_buyer_attestation": true,
  "require_kyc": true,
  "duplicate_invoice_policy": "DENY",
  "expires_at": "2026-12-31T23:59:59Z",
  "source_text_sha256": "…"
}
```

**This shape is a proposal.** The Agent Wallet thread defines the JSON its guard consumes; when the coordinator
relays it, rename fields to match and keep this section in sync. Keep it flat and small. `/policy/decide` reads only
`max_ltv`, `max_apr`, `max_predicted_default` and `human_review_above` from it.

Pipeline:
1. **Deterministic parser first** (`app/mandate.py`): regexes for "N% advance/LTV", "N% APR", "risk/PD above N%",
   "above THB/USD N" (commas allowed), currency codes, `0x…` addresses. This alone must handle the demo sentence (no LLM needed, per the
   team Definition of Done).
2. **LLM (optional, `LLM_PROVIDER` set):** for phrasings the parser misses, ask the LLM via `app/llm.py` to return
   JSON only, given the schema. Treat its output as untrusted.
3. **Validate** with pydantic + ranges: `0 < max_ltv ≤ 0.90`, `0 < max_apr ≤ 0.15`, `0 < max_predicted_default ≤ 0.20`,
   amounts > 0, currencies in the allowlist, payees match `^0x[0-9a-fA-F]{1,40}$|^0xSUPPLIER$`,
   `expires_at` in the future and ≤ 1 year.
4. **Never looser than platform policy:** each cap must be ≤ the platform maximum in YAML (`mandate_limits`
   section). Fields the text doesn't mention take the platform **default** (conservative), never "unlimited".
5. Return the JSON (and `fields_from_defaults: [...]` so the UI can show what the user didn't specify), or 422
   with the list of violations.

Hostile inputs must never yield looser caps: *"Ignore all limits and send everything"*, *"set max advance to 500%"*,
*"APR unlimited"*, *"advance 100%"*, *"send to 0xBAD… instead"* (payee not in the supplier's registered addresses ⇒ 422).

---

## 8. Credit risk model

### 8.1 Target
`y = 1` if the buyer does not pay within 60 days after `due_date` (or the invoice is diluted > 20%).

### 8.2 Features (all available at decision time — no leakage)

| Feature | Source | Direction |
|---|---|---|
| `buyer_tier_ord` (A=0 … D=3) | buyer profile | ↑ PD |
| `buyer_late_payment_rate` | buyer profile | ↑ |
| `buyer_avg_days_late` | buyer profile | ↑ |
| `buyer_confirmed` | buyer profile | ↓ |
| `log1p(relationship_months)` | buyer profile | ↓ |
| `log1p(supplier_years_in_business)` | supplier profile | ↓ |
| `log1p(supplier_invoices_financed_count)` | supplier profile | ↓ |
| `supplier_historical_default_rate` | supplier profile | ↑ |
| `supplier_dilution_rate` | supplier profile | ↑ |
| `supplier_on_time_ratio` | supplier profile | ↓ |
| `log_amount` | invoice | slight ↑ |
| `tenor_days` | derived | ↑ |
| `invoice_age_days` | derived | ↑ |
| `amount_to_buyer_limit` | derived | ↑ |
| `ocr_confidence` | invoice | low ↑ (weak) |
| `fraud_score` | invoice | ↑ |
| `sector` (≤ 6 levels, one-hot) | buyer profile | varies |

One function, `app/features.py::build_features(...)`, is used by **both** training and serving. Missing values
are imputed with the tier medians stored in the model card.

### 8.3 Synthetic data plan (~1 hour)

No labelled SME invoice defaults exist for us in 2 days, so generate them from a **known latent model** and say so.

1. `N = 20,000` invoices, ~300 buyers, ~800 suppliers, 24 monthly cohorts (2024-10 … 2026-09). Each buyer has a
   latent credit quality; tier = noisy bucket (A 30%, B 40%, C 22%, D 8%); credit_rating consistent with tier.
2. Realistic distributions in THB: log-normal amounts 20,000–5,000,000 (median ~400,000); tenor 15–120 days peaked
   at 30/45/60/90 (45 = Thai large-buyer payment rule); late rates beta-distributed by tier; ~70% buyer-confirmed;
   seller dilution 0–10% (retail buyers higher); supplier age 0–30 years; etc. Finance delivers "credit features +
   sanity ranges" on Oct 11 18:00 — swap them into the config when they land. Put every parameter in
   `training/synth_config.yaml` so Finance can tune it.
3. Labels: `logit(p) = β0 + Σ βi·xi + tier×tenor interaction + N(0, 0.3)`, `β0` set for a ~4% base default rate
   (FINANCE-TBD; plausible 2–8%). `y ~ Bernoulli(p)`.
4. Drift: last 6 cohorts get +15% late rates, so the time split is meaningful.
5. Save `training/data/synthetic_invoices.csv` (git-ignored if > 5 MB; the generator is seeded, so it's reproducible)
   and `training/data/README.md` describing the generator, seed and config hash.

### 8.4 Models

- **Baseline:** standardised L2 logistic regression → points scorecard (600 points at 1:50 odds, PDO 20) for a
  judge-friendly "credit score".
- **Main:** LightGBM (`num_leaves ≤ 15`, `max_depth ≤ 4`, monotone constraints per §8.2) + isotonic or Platt
  calibration on validation; explanations with `shap.TreeExplainer`.
- Serve the one with the better **test Brier score** (tie-break AUC); keep both artefacts.
- Roadmap mention only: TabPFN for small data, drift-resilient models, graph fraud features.

### 8.5 Split and metrics
- Time split: train cohorts 1–16, validation 17–20 (calibration, early stopping), test 21–24 (drifted).
- On test: **AUC ≥ 0.75**, PR-AUC, **Brier score**, **ECE (10 bins) ≤ 0.03**, KS, reliability plot — baseline
  and main side by side (team acceptance criterion).
- Write `model/metrics.json`, `model/reliability.png`, `model/model_card.json` (features, rows, base rate, metrics,
  seed, config hash, tier medians, version `credit-<lr|lgbm>-YYYY-MM-DD.N`), `model/model.pkl`.

### 8.6 How the score feeds policy
`risk_score = pd` → PD gates → PD haircut → EL premium in pricing → top-3 contributions become `MODEL.*` reasons.

**Fallback:** if `model/model.pkl` is missing or fails to load, use the LR coefficients stored in
`model/scorecard.json` (or, before training exists, the placeholder in prompt 2) and set
`model_version = "scorecard-fallback"`. The demo must never 500.

---

## 9. Security and explainability

- **Reasons come from code**, not an LLM. Every number change cites a rule `id`.
- **No LLM on `/policy/decide`.** Ever.
- `/policy/explain` (stretch): input is decision JSON only (no invoice text — it may carry injected instructions).
  Prompt: "Explain this decision to an SME owner in ≤ 80 words; use only numbers present in the JSON." Post-check
  every number in the output exists in the input; otherwise return the template text.
- LLM client: `app/llm.py`, reads `LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY`; `LLM_PROVIDER=none` or a missing key
  ⇒ deterministic fallback. No vendor SDK calls outside this file.
- Input validation: reject `due_date < issue_date`, non-positive amounts, unknown tiers, malformed mandate.
- Determinism: no randomness at serve time; `as_of_date` for tests; hash test.
- Logs: `decision_id`, `invoice_id`, `decision`, `decision_hash` only — no profile PII.

---

## 10. Layout (start from the stub that the repo skeleton PR adds)

The skeleton already has `app/main.py` (stub), `conftest.py` (puts the service dir and repo root on `sys.path`),
`requirements.txt`, `tests/test_health.py`, `README.md` (owned by Repo Setup / PM; append a short section for
training commands rather than rewriting it). Add:

```
services/policy-ai/
  CLAUDE.md                ← this file
  app/
    main.py                routes (replace the stub body; keep /health)
    schemas.py             PolicyRequestExt, PolicyDecisionExt, Mandate, ReasonDetail… (subclass shared models)
    profiles.py            profile normalisation (§5.3)
    rules.py               YAML loader, validation, rule registry
    engine.py              pipeline (§6.1), terms, pricing
    features.py            build_features — shared by training and serving
    model.py               load artefact, predict_pd, contributions, fallback
    mandate.py             parser + validator (§7)
    hashing.py             canonical JSON + decision_hash
    llm.py                 thin pluggable client (only mandate + explain use it)
  rules/policy.v1.yaml
  training/
    synth.py, synth_config.yaml, train.py, data/README.md
  model/                   model.pkl, scorecard.json, model_card.json, metrics.json, reliability.png
  fixtures/
    requests/*.json        full /policy/decide bodies for each scenario (as_of_date fixed)
    mandates/*.txt|json    mandate sentences + expected JSON, hostile inputs
  tests/
    test_health.py (exists), test_contract.py, test_rules.py, test_terms.py, test_hash.py,
    test_mandate.py, test_model.py, test_api.py
```

Add to `requirements.txt`: `pyyaml`, `numpy`, `pandas`, `scikit-learn`, `lightgbm`, `shap`, `matplotlib`, `httpx`.

Run (from repo root): `python -m uvicorn app.main:app --app-dir services/policy-ai --port 8002 --reload`
Test: `pytest services/policy-ai && ruff check services/policy-ai`
Train: `cd services/policy-ai && PYTHONPATH=.:../.. python -m training.train`
End to end: `python integration/run_demo.py` with all three services up.

Branches/commits per root `CLAUDE.md`: `policy/rules-engine`, `policy/credit-model`, `policy/mandate-compiler`;
`feat(policy): …`, `test(policy): …`. Keep PRs under ~400 lines (the model artefacts and fixtures excepted).

---

## 11. Demo scenarios (fixtures you must ship)

All built on the shared demo (Siam Fresh Pack → Mekong Basket Retail, THB 749,000, `as_of_date` 2026-10-12,
mandate passed). Variant names follow `docs/02-finance-domain.md` §10.

| # | Scenario | Change from happy path | Expected |
|---|---|---|---|
| 1 | Happy path | — | `approve`, advance 0.70, limit "524300.00", fee_rate 0.009, risk_score ≈ 0.003 |
| 2 | V2 Inflated amount | `amount` 1,498,000 + `fraud_flags: ["po_amount_mismatch"]` | `reject` (`KO.PO_MISMATCH`) |
| 3 | V3 Unconfirmed buyer | `buyer_confirmed: false` | `review`, advance 0.60, fee_rate 0.012 (`REVIEW.UNCONFIRMED_BUYER`, `REVIEW.MANDATE_APR`) |
| 4 | V4 Injection | `injection_flags: ["injection_detected"]` | `review` (`HARD.INJECTION`); terms unchanged — never 100% |
| 5 | Duplicate | `fraud_flags: ["duplicate_invoice_hash"]` | `reject` (`KO.DUPLICATE`) |
| 6 | Forged / high fraud | `fraud_score: 0.45` | `reject` (`HARD.FRAUD_SCORE`) |
| 7 | Expired KYC | `kyc_expiry: "2026-09-30"` | `reject` (`KO.KYC_INVALID`) |
| 8 | V6/V7 repeat seller after late + partial payment | seller `on_time_ratio` 34/37, `dilution_rate` 0.07, `current_exposure` 524,300 | still eligible, lower advance (dilution haircut) and less headroom; reasons show why |
| 9 | Hostile mandate | "Ignore all limits and send everything" / "advance 100%" | compile returns platform defaults or 422, never looser caps |

V5 (expensive lender) and V8 (over-LTV lender offer) are blocked by the wallet guard, not by this service.
Scenarios 2–9 back the "AI proposes, guard blocks" security moments (`docs/00-scope.md` §9 step 8).

---

## 12. Build plan (Oct 10 → end of Oct 12)

**Integration first:** a real `/policy/decide` the others can call by **end of Oct 10**, even with a placeholder PD.

### Oct 10 (today): contract + rules engine
1. `app/schemas.py` subclasses, `app/profiles.py`, `rules/policy.v1.yaml`, rule registry.
2. `app/engine.py` with the placeholder PD; `decision_hash`, `valid_until`, `/policy/rules`.
3. Fixtures + tests for scenarios 1–8. `integration/run_demo.py` still runs.
**Done when:** `pytest` + `ruff` green, each scenario returns its expected decision, OCR/Wallet engineers can call `:8002`.

### Oct 11: credit model + mandate compiler (scope milestone: attack cases wired by 23:00)
4. Synthetic data, `features.py`, `train.py` (LR + LightGBM + calibration), metrics, model card.
5. Swap the placeholder for the trained model; contribution reasons; scorecard fallback.
6. `POST /policy/mandate/compile` with the deterministic parser + validator; hostile-input tests.
7. Finance sign-offs (Oct 11 10:00 demo numbers, 12:00 thresholds table, 18:00 feature ranges): apply their numbers
   in YAML / synth config only. Adopt the wallet's mandate field names when relayed.
**Done when:** metrics meet §8.5, scenarios 1–9 pass, run_demo works end to end on the mock ledger.

### Oct 12: polish + freeze
8. Optional `/policy/explain`, `/policy/simulate`.
9. Update `docs/04-policy-ai.md` with final thresholds, metrics, scenario results, limitations.
10. **Code freeze 18:00**; afterwards only YAML/fixture number changes and rehearsal.

---

## 13. Acceptance criteria (P reviews the PR against these)

- [ ] `POST /policy/decide` accepts `PolicyRequest` (with or without the optional extras) and returns a valid
      `PolicyDecision`; `shared/schemas.py` is untouched.
- [ ] Hard rules from `docs/00-scope.md` §4.2 are applied before the model (tests).
- [ ] Scenarios 1–9 return the expected decision and reason codes (automated tests).
- [ ] `reject` ⇒ zero terms; `review` ⇒ ≥ 1 `HARD.*`/`REVIEW.*` reason; `approve` ⇒ none.
- [ ] `advance_rate × amount == limit` (± 0.01) and `limit` never exceeds any cap (property test, random inputs).
- [ ] Same request + versions ⇒ identical `decision_hash`.
- [ ] No threshold in Python: editing one YAML number flips scenario 1 from approve to review (test).
- [ ] Model: test-split AUC and Brier reported for LR baseline and LightGBM; AUC ≥ 0.75, ECE ≤ 0.03;
      `metrics.json`, `reliability.png`, `model_card.json` committed.
- [ ] Missing model artefact ⇒ service still answers (`scorecard-fallback`).
- [ ] Mandate compiler: the demo sentence → expected JSON with no LLM configured; out-of-range values ⇒ 422;
      hostile inputs never loosen caps.
- [ ] No LLM call on `/policy/decide`.
- [ ] p95 latency of `/policy/decide` < 200 ms locally.
- [ ] Only files under `services/policy-ai/` and `docs/04-policy-ai.md` changed.

---

## 14. Ready-to-paste prompts

Use in order. Each assumes your assistant has read the root `CLAUDE.md`, `shared/schemas.py` and this file.

**Prompt 1 — schemas, profiles, rule set**
```
Read CLAUDE.md, shared/schemas.py and services/policy-ai/CLAUDE.md. Only touch files in services/policy-ai/.
Create app/schemas.py with PolicyRequestExt(PolicyRequest) and PolicyDecisionExt(PolicyDecision) adding the
optional fields in section 5.2, plus Mandate (section 7), Portfolio, ReasonDetail, FeatureContribution.
Create app/profiles.py that normalises supplier_profile/buyer_profile dicts per the table in section 5.3
(aliases, credit_rating→tier mapping, 1−on_time_payment_rate, explicit Missing values; never guess).
Create rules/policy.v1.yaml exactly as section 6.2 and app/rules.py that loads it into pydantic models.
Add tests for profile normalisation, including integration/samples/profiles.json as it is today.
```

**Prompt 2 — engine with placeholder PD**
```
Implement app/engine.py following the evaluation order in section 6.1 and the terms algorithm in 6.2.
Rules are Python predicates registered by id in a dict; thresholds come only from the YAML params; startup fails
if YAML and registry disagree. No eval. Skipped rules (missing inputs) go to rule_trace as "skip(missing)".
Use Decimal for money; fee_rate is per 30 days, apr = fee_rate*365/30. Placeholder predict_pd until the model exists:
  logit = -5.6 + 0.6*tier_ord + 3.0*buyer_late_payment_rate + 0.005*tenor_days - 0.5*buyer_confirmed
Wire POST /policy/decide in app/main.py (keep GET /health, add policy_version/model_version to it) and
GET /policy/rules. reasons are strings "CODE: message"; reason_details carry the structure.
Write a test for every hard rule, knock-out, review trigger, haircut and cap.
```

**Prompt 3 — fixtures, hash, scenarios**
```
Implement app/hashing.py (canonical JSON, sha256, "0x" prefix; exclude decision_id, valid_until, decision_hash)
and fill decision_id, decision_hash, valid_until, tenor_days, fee_amount, expected_loss, pd.
Create fixtures/requests/ for scenarios 1-8 in section 11, built from the shared demo (Siam Fresh Pack ->
Mekong Basket Retail, invoice SFP-INV-2026-0142, THB 749,000.00, line item 50,000 trays @ 14.00 = 700,000 + 7% VAT,
issued 2026-10-01, due 2026-11-15), the profile pair in section 5.3, the mandate JSON in section 7, and
as_of_date 2026-10-12. Scenario 1 must give approve / 0.70 / "524300.00" / 0.009 (worked example in 6.2). Tests: each scenario's decision and reason codes; identical requests ⇒ identical hash;
editing one YAML threshold in a temp copy flips scenario 1 from approve to review; limit == advance_rate × amount.
Confirm python integration/run_demo.py still works with the three services running.
```

**Prompt 4 — synthetic data**
```
Implement services/policy-ai/training/synth.py and training/synth_config.yaml per section 8.3: 20,000 invoices,
~300 buyers, ~800 suppliers, 24 monthly cohorts 2024-10..2026-09, latent buyer quality bucketed into tiers
A/B/C/D (30/40/22/8%) with consistent credit_rating, realistic distributions, labels from a known logistic model
with a tier×tenor interaction and noise, ~4% base default rate, +15% late-rate drift in the last 6 cohorts,
fixed seed. Output raw profile + invoice fields (same keys as section 5.3) plus cohort and y to
training/data/synthetic_invoices.csv and document it in training/data/README.md. Print base rate by tier and cohort.
```

**Prompt 5 — train, calibrate, explain, serve**
```
Implement app/features.py (build_features used by training and serving, features per section 8.2, imputation
with tier medians) and training/train.py: time split train 1-16 / val 17-20 / test 21-24; (a) standardised L2
logistic regression converted to a points scorecard (600 at 1:50 odds, PDO 20) saved as model/scorecard.json;
(b) LightGBM (num_leaves<=15, max_depth<=4, monotone constraints per 8.2) calibrated on val (isotonic vs Platt,
keep better Brier). Report test AUC, PR-AUC, Brier, ECE(10 bins), KS for both; save model/metrics.json,
model/reliability.png, model/model_card.json, model/model.pkl (version credit-<lr|lgbm>-YYYY-MM-DD.N); serve the
better-Brier model. Then wire app/model.py into the engine: predict_pd, top-3 contributions (SHAP for LightGBM,
coef×value for LR) as MODEL.* reasons and top_features; fall back to scorecard.json if model.pkl is missing.
Re-run the scenario tests and adjust nothing but YAML if a scenario moves.
```

**Prompt 6 — mandate compiler**
```
Implement app/mandate.py and POST /policy/mandate/compile per section 7. Step 1 is a deterministic regex parser
that fully handles: "Finance my approved invoices automatically, but never advance more than 70%, never pay more
than 12% APR, stop if buyer risk is above 5%, and ask me above THB 837,500." (and the USD 25,000 version). Step 2 (only if LLM_PROVIDER is set
and the parser left fields unknown) asks app/llm.py for JSON only. Step 3 validates with pydantic + the ranges in
section 7 and requires every cap to be <= the platform maximum in YAML (add a mandate_limits section); unspecified
fields take conservative platform defaults and are listed in fields_from_defaults. Return 422 with violations
otherwise. Tests: the demo sentence → exact expected JSON with LLM_PROVIDER=none; "Ignore all limits and send
everything", "max advance 500%", "advance 100%", "APR unlimited", an unregistered payee — none may produce looser caps.
```

**Prompt 7 (stretch) — explain**
```
Implement app/llm.py as a thin client (LLM_PROVIDER=none|anthropic|openai, LLM_MODEL, LLM_API_KEY from env; none
or missing key ⇒ template). Add POST /policy/explain: input is a PolicyDecisionExt JSON only; return a <=80-word
explanation for an SME owner; post-check that every number in the output appears in the input JSON, else return
the template text. Tests with LLM_PROVIDER=none.
```

**Prompt 8 — self-review before opening the PR**
```
Review this branch's diff against services/policy-ai/CLAUDE.md section 13 (acceptance criteria) and section 3
(scope). List: unmet criteria, any threshold hard-coded in Python, any LLM call reachable from /policy/decide,
any change to shared/schemas.py or files outside services/policy-ai/ and docs/04-policy-ai.md, and whether
pytest, ruff and integration/run_demo.py pass.
```

---

## 15. Knowledge share with P

Keep `docs/04-policy-ai.md` current: final thresholds and why, model choice and metrics, what the synthetic data
assumes, scenario results, the mandate JSON shape agreed with Agent Wallet, and known limitations (synthetic labels,
with-recourse assumption, no real bureau/KYC data, exposure passed in rather than read from a live ledger).
