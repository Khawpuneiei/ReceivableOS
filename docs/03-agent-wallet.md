# 03 · Agent Wallet and Agent Guardrails

> **Who this is for:** P (PM) and anyone who needs the wallet in one read. The Agent AI engineer keeps the
> **Status** table at the bottom current. The full build brief, contract specs and ready-to-paste prompts are in
> [`services/agent-wallet/CLAUDE.md`](../services/agent-wallet/CLAUDE.md); the attack test set is
> [`services/agent-wallet/eval/cases.jsonl`](../services/agent-wallet/eval/cases.jsonl).

## 1. What the agent wallet is

The only component in ReceivableOS that holds keys and moves money. It turns a credit decision into on-chain money
movements (register the invoice, record the approval, draw the advance, settle when the buyer pays), but only inside
a **mandate** the SME set and the agent cannot change. It also owns all Solidity: `MockStable` (tTHB),
`ReceivableRegistry`, `FinancingVault`, `PolicyGuard`, `AgentWallet`, on FISCO BCOS with a mock ledger fallback.

One sentence for the pitch: **the AI proposes, deterministic code and the mandate decide, the contracts enforce,
and a human approves anything large, so a hijacked or wrong AI produces a red "BLOCKED" row, not a payment.**

## 2. How a financing flows through it (demo numbers from `docs/02`)

| Tx | Call | Who signs | What it proves |
|---|---|---|---|
| setup | deploy, `PolicyGuard.setMandate` | owner (P) | the mandate is on-chain: 70% max advance, 12% max APR, 5% max PD, per-tx cap 1.5m, daily cap 3m, human review at or above THB 837,500 |
| TX‑3 | `Vault.deposit` | lenders (setup script) | lender liquidity is in the vault |
| TX‑1 | `Registry.register(fingerprint, docHash, seller, 749000, dueDate)` | agent via `AgentWallet` | the keyed invoice fingerprint from OCR is unique, so a re-saved PDF of the same invoice still reverts; the seller's payout address is bound now, from the payee registry, never from invoice text |
| TX‑2 | `Registry.approve(fingerprint, 524300, 1200 bps, decisionHash)` | risk-oracle key | policy-ai's exact decision (by hash) approved this limit |
| TX‑4 | `AgentWallet.execute → PolicyGuard.check → Vault.draw` | agent | draw 524,300 from Lender A (10.95% APR beats B's 65% advance); seller gets 516,705.14 after fees |
| TX‑5 | `AgentWallet.execute → Vault.repay` | agent | buyer paid 749,000: lender 524,300, seller reserve 224,700 |
| anchor | `AgentWallet.anchorAudit(root)` | agent | the off-chain audit log can't be rewritten later |

## 3. The six layers between an AI and the money

| Layer | Where | Stops |
|---|---|---|
| L0 Schema | wallet service | malformed amounts, wrong currency, demo bypass outside demo mode |
| L1 Provenance | wallet service | decision not `approve`, stale, or edited after policy-ai produced it (`decision_hash`) |
| L2 Injection scan | wallet service | instructions hidden in any text field (rules + Llama Prompt Guard 2 classifier + canary), incl. Thai, Chinese, base64, zero-width tricks |
| L3 Mandate & spending | wallet service | APR, advance vs face value, PD, per-tx and daily caps, payee/target allowlist, duplicate, already drawn, expiry, pause |
| L4 Human approval | wallet service + `AgentWallet.confirm` | anything at or above THB 837,500 waits for the approver (the Finance teammate; P sets the rules and can't approve payments) |
| L5 On-chain guard | `PolicyGuard`, `Vault`, `Registry` | the same limits again, enforced even if the whole Python service is compromised |

On stage, `DEMO_MODE` lets us skip L0–L4 for one request so judges see the **chain itself** revert a 19.5% APR draw
and an over-limit draw, each with its own tx hash.

What binds a fully stolen agent key (be precise if judges ask): contract and function allowlist, payee bound at
registration, approved limit, advance vs on-chain face value, per-tx and daily caps, expiry, pause, duplicate and
already-drawn checks. The APR the agent reports is also capped by the risk-oracle's approval, so lying about it takes
two keys.

**Known limit for the pitch:** in the MVP the risk-oracle key that signs TX‑2 may sit in the same process as the
agent key, so the wallet could in principle approve its own receivable. The brief asks the engineer to move it to
the orchestrator or policy-ai process if cheap; the production answer is policy-ai's own signer or an HSM.

## 4. Threats and the defenses we use

Threats: prompt injection through invoice text (A1), payee substitution ("our account changed"), instructions
smuggled in other services' outputs, tool misuse (agent tries to unpause or loosen its own mandate), oversized or
off-mandate payments (A3, A4, V5, V8), replay and double financing (A2), data exfiltration, decision tampering,
stolen agent key, obfuscated injections, expired mandate or paused wallet (A6).

State of the art we build on (2024–26): OWASP Top 10 for LLM apps (prompt injection, excessive agency), Google
DeepMind's CaMeL and the "design patterns for securing LLM agents" paper (plan-then-execute, quarantined LLM,
provenance of values), Microsoft's spotlighting, OpenAI's instruction hierarchy, Meta's Prompt Guard 2 and
LlamaFirewall, canary tokens, human-in-the-loop for money, smart-account guards (Safe, ERC‑4337 ideas) and the
AgentDojo way of measuring attack success. The shared lesson: **detectors miss things, so design the system so a
fully hijacked model still cannot move money**, and use detectors to catch attacks early and explain them.

Our concrete version: the LLM that reads invoices has no tools; payees only ever come from the registry and are
bound on-chain at TX‑1, so a value that came from untrusted text can never reach a payment; the agent key can call
one function; every limit is checked twice (Python and chain).

## 5. Attack test set and the number for the pitch

`eval/cases.jsonl` holds 51 cases: 40 attacks (A1–A6 from the architecture, Finance's V5 and V8, payee swaps incl. a
homoglyph, tampered and stale decisions, injections in English, Thai, Chinese, base64 and zero-width form, canary
leak, replay, schema abuse, privilege attempts, the owner trying to approve a payment, two agent-loop cases) and 11 benign cases (happy paths, the large
invoice that should wait for approval incl. the exact 837,500 boundary, settlement incl. dilution, late and short pay, benign text that mentions
payments). `eval/run_eval.py` reports:

| Metric | Target |
|---|---|
| Unauthorized payments (attack success rate) | **0%** |
| Attacks caught (blocked or sent to a human) | 100% |
| Which layer stopped each attack | funnel chart for the slide |
| Injection scanner alone (recall) | reported honestly; below 100% is expected and is the argument for layering |
| Benign cases wrongly blocked | ≤ 10% |
| Benign cases completed | ≥ 90% |

Slide line: *"We attacked our own agent 40 ways. The scanner alone caught X%; the full stack let zero unauthorized
payments through, and the APR and over-limit attempts have on-chain revert hashes."*

## 6. Interfaces (details in the service CLAUDE.md §6)

`POST /wallet/register`, `/wallet/approve`, `/wallet/execute`, `/wallet/settle`, `/wallet/mandate/activate`,
`/wallet/confirm/{tx_id}` (human approval, approver token only), `/wallet/pause|unpause`, `GET /wallet/audit/{invoice_id}`, `/health`.
Tx result: `tx_id, status (executed | blocked | pending_approval | failed), chain, chain_ref, approvals_required,
block_reason, audit_ref`. Mock hashes are prefixed `mock:` so nobody mistakes them for chain hashes.

## 7. Decisions so far and what's still open

Settled (via the coordinator): tTHB as default token (P may still switch to mock USDC); `blocked`/`failed` statuses are
in `shared/schemas.py`; demo caps THB 1,500,000 per transaction and 3,000,000 daily, human review at or above
837,500, all THB with 2 decimals; `POST /wallet/confirm/{tx_id}` for human approval; readable revert strings;
MVP freeze Sun 12 Oct 12:00 on the mock ledger; real FISCO BCOS hashes (mandatory for the submission) land
13–15 Oct, final documents 16–17 Oct, early upload 18 Oct, final submission 20 Oct 22:59; Base Sepolia deploy of
the same contracts is an optional extra for the on-chain bonus points; mandate fields `max_ltv`, `max_apr`, `max_predicted_default`, `human_review_above`,
`max_amount_per_tx`, `daily_cap` (policy-ai's shape); `risk_score` is the buyer PD; registry dedupes on the keyed
`invoice_fingerprint` from OCR.

Still open for P: final tTHB vs USDC; who holds the approver key (default: the Finance teammate); whether to move the
risk-oracle key out of the wallet process before freeze; whether to spend 18–20 Oct on the Base Sepolia bonus deploy.

Security self-assessment: the permission tiers come from CLAUDE.md section 5.1 (plus role checks in 5.6), the
controls from 5.4 and the eval funnel, and the known risks from the note in section 3 above plus detector recall,
file-based keys and a single approver. Mapping in `docs/01-architecture.md` section 2.1.

## 8. Status (engineer updates)

| Item | Status |
|---|---|
| Contracts + Foundry tests | Done locally: five contracts compile with solc 0.8.11, 23 Foundry tests pass. Not deployed. PR #17 |
| Mock ledger + endpoints | Done: register, approve, execute, settle, confirm, pause, mandate, audit, holds. 102 pytest tests pass. PR #17 |
| FISCO chain + deploy (due 15 Oct) | Not started. Needs a Docker-hosted FISCO node (download approval pending). No deploy script or FISCO adapter yet |
| Guard L0–L4 | Done for draws: L0–L4 checks, hold-for-approval, hash-chained audit log, anchoring at settlement |
| Eval: ASR / catch rate / scanner recall | Seed set (guard on): ASR 0/38, caught 38/38, benign blocked 0/11. Held-out v3 (rules only): caught 14/24. The classifier is audit-only by default |
| Demo tx hashes (TX‑1…TX‑5, 2 reverts, anchor) | 0 on chain of 8. The mock demo runs 15 steps: 11 go through the mock chain and 4 are stopped off-chain (`eval/demo_tx_hashes.md`) |
