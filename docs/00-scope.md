# 00 — ReceivableOS Scope, Ownership and Plan

> **Read this first.** This is the PM's source of truth for what we build before the internal deadline (end of Oct 12, Bangkok time).
> Paste this whole file into your AI assistant together with your module doc (`docs/03`, `04` or `05`) before you start coding.
> Status: **v0.1 draft, 2026-10-10.** Lines marked **[OPEN]** are waiting on a decision from P (PM). When P decides, this file is updated and the decision moves to the Decision log at the bottom.

---

## 1. One-line pitch

**ReceivableOS turns an AI from a financial adviser into a bounded financial counterparty:** it reads an SME invoice, checks it for fraud and prompt injection, prices the credit risk, and then its wallet draws financing on-chain, but only inside a mandate that an on-chain guard enforces, so a wrong or manipulated AI decision is reverted, not paid.

Pipeline we demo:

```
invoice upload → OCR + injection scan + fraud score → credit decision (approve / review / reject, advance rate, fee)
→ wallet proposes financing → policy guard checks mandate → on-chain draw → "buyer paid" → on-chain settlement
```

Why it fits the competition: the 2026 Shenzhen FinTechathon International Track topic is **"Agent Wallet – AI Agent Digital Wallet"** (organised by IEEE CIS Shenzhen with WeBank). Our design notes cite the rules as weighting **task completion 40%, security/compliance 30%, innovation/interaction 30%**, and requiring **real on-chain transaction hashes** in the submission. Past FinTechathon entries (github.com/FISCO-BCOS/hackathon) deploy Solidity contracts on **FISCO BCOS** and document contract calls with console / python-sdk screenshots.

Background reading (in the project folder, not the repo): `ReceivableOS-Idea+Architect.md` (design and research) and `receivableos_specialization_roadmap.md` (learning roadmap, Thai).

---

## 2. In scope / out of scope (hackathon MVP)

| In scope (must exist by Oct 12) | Out of scope (say "production roadmap" in the pitch) |
|---|---|
| Invoice OCR from PDF/image into a typed JSON invoice | Real ERP, bank, e-invoice or logistics integrations |
| Prompt-injection detection on invoice text before any LLM reasoning | Federated learning, TEE, zkML, MPC / threshold signing |
| Document-level fraud score (tampering, math errors, mismatches, duplicates) | Graph neural networks trained on real supply-chain data |
| Credit risk score from a small tabular model with a transparent baseline | Real borrower data; any real PII anywhere |
| Rule-based credit decision: approve / review / reject, advance rate, fee | Legal enforceability of the token (label as "simulated receivable claim") |
| Natural-language mandate compiled into a validated JSON policy | Real KYC/AML provider (we mock a KYC credential flag) |
| Agent wallet that proposes, policy-checks, and executes on-chain | Secondary market, investor pools, ERC-3643 / ERC-3525 full standards |
| Contracts on FISCO BCOS: receivable registry (duplicate-invoice block), financing vault, policy guard, mock stable token | Safe / ERC-4337 (not native to FISCO BCOS; described as the EVM-chain production path) |
| Mock ledger fallback so the demo never blocks on the chain | Mainnet anything |
| Two mock lenders with quotes; wallet picks the best within mandate | Live pricing, real lenders |
| "Buyer paid" trigger and automatic settlement to the lender | Real payment oracle |
| One demo screen, synthetic invoices including fraud and injection samples | Mobile app, multi-tenant auth |
| At least one **blocked** transaction shown on screen (guard revert) | |
| One evaluation number per module | |

Rules that hold everywhere:
- **LLM output never becomes calldata directly.** Every AI output is typed JSON, validated by deterministic code, then checked by the policy guard.
- **Invoice text is untrusted data.** It is never concatenated into an LLM system or tool prompt without the injection scan and clear data delimiters.
- **No PII on chain.** Only hashes, ids, amounts, statuses and decision hashes.
- **Every executed or blocked action has an audit record** (decision hash, policy version, model version, tx hash or revert reason).

---

## 3. Module ownership map

Team: P (PM, also AI engineer), Finance, three AI engineers.

| # | Module | Owner | Repo path | Knowledge doc |
|---|---|---|---|---|
| 1 | Scope, PR review, **integration** (orchestrator, UI wiring to services), submission | **P (PM)** | `docs/00-scope.md`, `shared/schemas.py`, `integration/` | this file |
| 2 | Finance domain, pain-point numbers, business model, demo story numbers | **Finance** | `docs/02-finance-domain.md` | `docs/02` |
| 3 | Agent wallet + agent-injection guardrails + mandate enforcement + **the whole on-chain layer** (`AgentWallet`, `PolicyGuard`, `ReceivableRegistry`, `FinancingVault`, settlement token, deployment, mock ledger) | **Agent AI eng** | `services/agent-wallet/`, `services/agent-wallet/contracts/` | `docs/03`, `docs/01` |
| 4 | Credit risk model + credit decision (approve/review/reject, advance rate, fee) + NL mandate → policy JSON | **Policy AI eng** | `services/policy-ai/` | `docs/04` |
| 5 | Invoice OCR + OCR injection detection + document fraud detection | **OCR AI eng** | `services/ocr-ai/` | `docs/05` |
| 6 | **Demo data**: each engineer builds the samples for their own module (OCR: invoices incl. injection/fraud/duplicate; Policy: supplier/buyer profiles and credit data; Agent: mandates, lender quotes, attack transactions). P rechecks them against the `docs/02` scenario | **Agent + OCR + Policy AI engs**, P rechecks | `data/` per module | `docs/02` |
| 7 | **Demo UI design** (one screen, port 3000) | **Policy AI eng** (P wires it to the orchestrator) | `ui/` | this file |
| 8 | **Pitch pack**: deck, video, README in submission shape, business plan | **P + Policy AI eng + Finance** | `pitch/` | `docs/02` |
| 9 | Controls and compliance research: wallet spending limits, human approval, audit log, one-line KYC/AML and data-privacy stance | **P (PM)** | `docs/06-controls-and-compliance.md` | `docs/06` |
| 10 | Architecture and research | Research thread → P | `docs/01-architecture.md` | `docs/01` |

Load check: the Policy AI eng now carries the credit model, the UI design and part of the pitch. If their model slips on Oct 11, the UI falls back to P and the pitch to Finance + P.

Terminology fix, because two things are called "policy":
- **Credit policy** = the underwriting decision (Policy AI eng). Output: `decision`, `advance_rate`, `limit`, `fee_rate`.
- **Mandate / guard policy** = the limits the wallet may act within (max LTV, max APR, max amount, allowed payees, KYC required, duplicates denied). The Policy AI eng owns the **schema** and the NL → JSON compiler; the Agent AI eng owns **enforcement** (off-chain check + on-chain `PolicyGuard`).

---

## 4. Interfaces (the contract between modules)

All services: Python 3.11, FastAPI, JSON over HTTP. LLM calls go through a thin pluggable client (`llm_client.complete(messages, schema)`), never a vendor SDK called directly from business logic. Money is a **string decimal** in JSON (`"749000.00"`) to avoid float errors; currency is ISO 4217 (`"THB"` for the demo, per `docs/02`). `fee_rate` is per 30 days; `risk_score` is 0 to 1, higher is riskier (both pending Policy confirmation). Lender quotes and the guard compare **APR**; the wallet converts `fee_rate` to APR with the shared helper in `shared/money.py`, never with its own formula. On chain, amounts are integers in the mock stable token's smallest unit; the conversion lives in one helper owned by the wallet (see `docs/03`).

### 4.1 OCR service — `POST /ocr/extract`
Input: multipart `file` (PDF/PNG/JPG). Output:
```json
{
  "invoice_id": "inv_0001",
  "supplier": {"name": "Siam Fresh Pack", "tax_id": "0105559000000"},
  "buyer": {"name": "Mekong Basket Retail", "tax_id": "0107559000001"},
  "invoice_no": "INV-2026-0142",
  "issue_date": "2026-09-15",
  "due_date": "2026-11-14",
  "amount": "749000.00",
  "currency": "THB",
  "line_items": [{"description": "Packaged fresh produce", "qty": 1000, "unit_price": "749.00", "total": "749000.00"}],
  "confidence": 0.94,
  "injection_flags": [],
  "fraud_score": 0.07,
  "fraud_flags": [],
  "doc_hash": "sha256:...",
  "invoice_fingerprint": "sha256:..."
}
```
Two hashes, both additions to the base contract: `doc_hash` is sha256 of the file bytes (audit trail); `invoice_fingerprint` is a hash of the normalised invoice content (exact fields defined in `docs/05`). **Duplicate detection keys on `invoice_fingerprint`**, because re-saving a PDF changes `doc_hash`. See `docs/05`.

### 4.2 Policy service — `POST /policy/decide`
Input: `{ "invoice": <4.1 output>, "supplier_profile": {...}, "buyer_profile": {...} }`. Output:
```json
{
  "decision": "approve",
  "advance_rate": "0.70",
  "limit": "524300.00",
  "fee_rate": "0.009",
  "risk_score": 0.18,
  "reasons": ["buyer PD below 5% cap", "fraud_score 0.07 below 0.30 cap"],
  "model_version": "credit-v0.1",
  "policy_version": "mandate-v0.1"
}
```
Hard rules the policy service must apply before any model: `injection_flags` non-empty → `review`; `fraud_score ≥ 0.30` → `reject`; `confidence < 0.80` → `review`.

### 4.3 Agent wallet — `POST /wallet/execute`
Input: `{ "decision": <4.2 output>, "payee": "0x...", "amount": "524300.00", "currency": "THB", "invoice_id": "inv_0001" }`. Output:
```json
{
  "tx_id": "tx_...",
  "status": "executed",
  "chain_ref": "0x<tx hash on FISCO BCOS, or mock:...>",
  "approvals_required": 0,
  "audit_ref": "audit_..."
}
```
`status` ∈ `executed | blocked | pending_approval | failed`. A `blocked` result carries the guard's revert reason in the audit record. Above the mandate's `human_review_above` amount the wallet returns `pending_approval` and `approvals_required: 1`.

The wallet also exposes `register`, `approve`, `settle`, `mandate/activate` and `audit` endpoints (proposed by the Architect, `docs/01`); their exact shapes are in `shared/schemas.py`.

### 4.4 Orchestrator (P) — glue, owned by the PM seat
Stub lives in `integration/run_demo.py`. `POST /flow/run` takes an uploaded invoice and a mandate id, calls 4.1 → registry duplicate check → 4.2 → lender quotes → 4.3, and returns every intermediate result for the UI. `POST /flow/repay` simulates "buyer paid" and triggers settlement. Ports: orchestrator 8000, ocr 8001, policy 8002, wallet 8003, UI 3000.

The code version of this contract is the Pydantic models in `shared/schemas.py`, owned by P. If this section and that file disagree, `shared/schemas.py` wins and this section gets fixed.

Rule for changing an interface: open a PR titled `contract: ...` that changes only `shared/schemas.py` (and this section), get P's approval, and only then change service code. No silent field renames.

---

## 5. Timeline and checkpoints (Bangkok time)

| When | Checkpoint | Who | Evidence |
|---|---|---|---|
| **Fri Oct 10, by 14:00** | Knowledge docs `01`–`05`, this scope, repo skeleton and per-service `CLAUDE.md` merged | P + threads | PRs merged |
| Oct 10, 14:00 | 15-min kickoff: walk the pipeline, confirm interfaces, answer [OPEN] items | all | Decision log updated |
| Oct 10, by 22:00 | Each service runs locally and returns **stubbed** JSON matching section 4; contracts compile | each owner | `curl` screenshot in PR |
| **Sat Oct 11, by 10:00** | Finance teammate approves the demo scenario numbers in `docs/02` | Finance | comment on PR #3 |
| Oct 11, by 12:00 | First real logic: OCR extracts 5 sample invoices; credit model trained on synthetic data; wallet executes one tx on chain or mock | each owner | PR + sample output |
| Oct 11, by 18:00 | **First end-to-end run** through the orchestrator (happy path) | P | demo log |
| Oct 11, by 22:00 | Finance teammate's 2 to 3 page business-plan draft (problem, market, business model, risk) | Finance | PR per `docs/02` |
| Oct 11, by 23:00 | Attack cases wired: injection invoice, forged invoice, duplicate invoice, APR over mandate, payee not allowlisted | all | each blocked with a reason |
| **Sun Oct 12, by 10:00** | Demo data set final, UI shows the full flow, eval numbers computed | P, Finance, owners | numbers in `docs/` |
| **Oct 12, 12:00** | **Code freeze.** After this, only bug fixes P approves | all | tag `v0.1-freeze` |
| Oct 12, 12:00–18:00 | Deck, 3-minute video, README in submission shape, tx hash list | Finance + P | `pitch/` |
| Oct 12, 18:00–21:00 | Two full rehearsals with a fresh clone | all | recording |
| Oct 12, by 23:59 | Submit / internal deadline met | P | link |

Daily stand-up in chat at 09:00 and 21:00: what merged, what is blocked, what is next.

---

## 6. Definition of done per module

A module is done when **all** of its lines are true and shown in a merged PR.

**OCR AI**
- [ ] `POST /ocr/extract` returns the 4.1 schema for every file in `data/invoices/` (≥ 10 synthetic invoices, including ≥ 2 injection, ≥ 3 fraud, 1 duplicate).
- [ ] Field-level accuracy reported on the labelled set (target ≥ 90% on amount, dates, invoice_no, parties).
- [ ] Injection samples produce non-empty `injection_flags`; clean samples produce none (report catch rate and false-positive rate).
- [ ] Fraud samples score above the reject threshold; report catch rate.
- [ ] Works offline with a fallback path if the LLM/vision API is down (cached results for the demo set is acceptable).

**Policy AI**
- [ ] `POST /policy/decide` returns the 4.2 schema; hard rules in 4.2 applied before the model.
- [ ] Credit model trained on a documented synthetic or public dataset; **AUC and Brier score** reported with a time-based or holdout split; baseline (logistic regression) reported next to it.
- [ ] `reasons` are human-readable and cite the rule or top features.
- [ ] NL mandate → JSON compiler: given the sample sentence in section 9, outputs the mandate JSON and rejects out-of-range values with an error.

**Agent wallet**
- [ ] `POST /wallet/execute` returns the 4.3 schema on chain and in mock mode (`LEDGER_MODE=fisco|mock`, default `mock`).
- [ ] Off-chain pre-check and on-chain `PolicyGuard` both enforce: max amount, max advance rate, max fee/APR, payee allowlist, KYC flag, duplicate invoice, mandate expiry.
- [ ] Agent-injection test suite: ≥ 10 adversarial cases (instruction in invoice text, payee swap, amount inflation, tool-call smuggling); report how many are stopped and **where** (scanner, deterministic validator, guard).
- [ ] Human approval path above the threshold.
- [ ] Every call writes an audit record; demo shows ≥ 5 real tx hashes and ≥ 1 blocked attempt.

**Contracts / chain (Agent AI eng)**
- [ ] `ReceivableRegistry` (register fingerprint, reject duplicates), `FinancingVault` (fund, draw, repay, settle), `MockStable` token, plus wallet/guard from `docs/03`.
- [ ] Deployed to a FISCO BCOS node (local 4-node build_chain or a provided test chain); addresses in `contracts/deployments.json`.
- [ ] Unit tests for the revert paths; interface doc with call screenshots (past-winner submission convention).

**Integration (PM) + UI (Policy AI eng designs, P wires)**
- [ ] One command starts everything (`make demo` or `docker compose up`).
- [ ] The UI shows: uploaded invoice, extracted fields, flags, risk score + reasons, lender quotes, guard result, tx hashes with links/ids, and a red "BLOCKED" row.
- [ ] Happy path and 3 attack paths run from a fresh clone in under 5 minutes.

**Finance**
- [ ] `docs/02` with cited pain-point numbers, glossary, the demo story numbers (invoice amount, advance rate, fees, lender quotes) and a one-slide business model (who pays, take rate, unit economics).

---

## 7. PR review checklist (for P)

Copy into each review. A "no" on any **bold** line blocks the merge.

1. **Is this in the In-scope column of section 2?** If it is in Out of scope, close or move to a `later/` note.
2. **Does it match `shared/schemas.py` exactly** (field names, types, money as strings, status enums)? Any schema change comes in its own `contract:` PR first.
3. **Does any LLM output reach the wallet or calldata without a deterministic validator?** Must be no.
4. **Does any invoice text reach an LLM prompt without the injection scan and data delimiters?** Must be no.
5. **Any secret, private key, API key or real personal data committed?** Must be no (`.env` only, `.env.example` updated).
6. Does it run with the mock fallback (no chain, no LLM key)?
7. Does it include a test or a sample request/response in the PR description?
8. Does it log an audit record for every decision or transaction it makes?
9. Is the change small enough to review in 10 minutes? If not, ask to split.
10. After Oct 12 12:00: is it a bug fix for the demo? If not, it waits.

---

## 8. Risks and fallbacks

| Risk | Likelihood | Fallback |
|---|---|---|
| FISCO BCOS node setup eats hours | High | Mock ledger in `LEDGER_MODE=mock` (the default) from day one; one person (contracts owner) brings up a local 4-node chain with `build_chain.sh` in parallel. Real tx hashes are required for submission, so the chain must work by Oct 12 morning. |
| LLM / vision API down or rate-limited during demo | Medium | Cache responses for the demo invoice set; pluggable client can point to a local model. |
| OCR accuracy weak on photos | Medium | Demo on clean generated PDFs; show photo case as stretch. |
| No real credit data | Certain | Synthetic data generator with documented assumptions plus a public credit dataset for the model; say so openly. |
| Integration slips because three silos drift | High | Stubs matching section 4 by Oct 10 22:00; first end-to-end Oct 11 18:00; P owns the orchestrator. |
| Scope creep (GNNs, ZK, ERC-4337) | High | Section 2 table; PR checklist line 1. |
| Rules require something we did not plan (format, language, chain) | Medium | [OPEN] P confirms the rule PDF details (see Decision log). |
| A teammate drops out | Low | Each `services/*/CLAUDE.md` lets another engineer continue with their AI. |

---

## 9. Demo story

The canonical scenario, numbers and the eight attack variants live in **`docs/02-finance-domain.md`** (Finance owns them; approval due Sat Oct 11, 10:00). Summary so every module uses the same values:

1. Siam Fresh Pack (SME supplier) uploads a THB 749,000 invoice to Mekong Basket Retail (buyer), due in 45 days.
2. Mandate in plain language: max 70% advance (LTV), APR at most 12%, buyer PD at most 5%, human review above THB 837,500. The compiler shows the JSON.
3. OCR extracts fields; no injection; fraud score low. Registry confirms the invoice is not financed elsewhere.
4. Credit decision: approve, advance_rate 0.70, limit THB 524,300, fee_rate 0.009 per 30 days, risk_score 0.18.
5. Two mock lenders quote: Lender A 70% at 10.95% APR, Lender B 65% at 9.13% APR. The wallet picks Lender A (highest advance within the APR cap).
6. Guard passes, wallet draws on chain. Tx hash shown.
7. "Buyer paid" → wallet settles the lender automatically. Tx hash shown.
8. Attacks from `docs/02` (at least: hidden injection text with a swapped payee, duplicate invoice, quote above the APR cap) → each blocked; one is proposed by the AI and **reverted by the on-chain guard**, shown as a red row.

Target slide: 5 green tx hashes (register, create position, lender funds vault, agent draws, agent settles) and 1 red blocked attempt.

---

## 10. Decision log

| Date | Decision | By |
|---|---|---|
| 2026-10-10 | Stack: Python 3.11 + FastAPI per service, JSON over HTTP, pluggable LLM client | coordinator default |
| 2026-10-10 | Chain: FISCO BCOS with mock ledger fallback (replaces Base Sepolia / Safe in the design notes) | [OPEN] P to confirm |
| 2026-10-10 | Oct 12 is the team's internal MVP deadline; the public announcement lists the preliminary round closing Nov 2 | [OPEN] P to confirm |
| 2026-10-10 | Lender quotes, settlement trigger and KYC mock live in the orchestrator (PM) | [OPEN] P to confirm |
| 2026-10-10 | Agent AI eng owns the whole on-chain layer (all contracts, in `services/agent-wallet/contracts/`) | P |
| 2026-10-10 | Integration: PM. Demo data: each engineer for their module, PM rechecks. Demo UI design: Policy AI eng. Pitch pack: PM + Policy AI eng + Finance. Controls/compliance research: PM (`docs/06`) | P |
| 2026-10-10 | Settlement token on chain: simulated THB token `tTHB` (Finance doc) instead of USDC (architecture doc) | [OPEN] P to confirm |
| 2026-10-10 | `fee_rate` is per 30 days; `risk_score` is 0 to 1, higher is riskier | [OPEN] Policy eng to confirm |
| 2026-10-10 | Demo scenario and numbers come from `docs/02` (THB, Siam Fresh Pack → Mekong Basket Retail) | Finance thread; Finance teammate to approve by Oct 11 10:00 |
