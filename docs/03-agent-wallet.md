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
| setup | deploy, `PolicyGuard.setMandate` | owner (P) | the mandate is on-chain: 70% max advance, 12% max APR, 5% max PD, human review above THB 837,500 |
| TX‑3 | `Vault.deposit` | lenders (setup script) | lender liquidity is in the vault |
| TX‑1 | `Registry.register(docHash, seller, 749000, dueDate)` | agent via `AgentWallet` | invoice fingerprint is unique (duplicates revert); the seller's payout address is bound now, from the payee registry, never from invoice text |
| TX‑2 | `Registry.approve(docHash, 524300, 1200 bps, decisionHash)` | risk-oracle key | policy-ai's exact decision (by hash) approved this limit |
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
| L4 Human approval | wallet service + `AgentWallet.confirm` | anything above THB 837,500 or carrying risk flags waits for P |
| L5 On-chain guard | `PolicyGuard`, `Vault`, `Registry` | the same limits again, enforced even if the whole Python service is compromised |

On stage, `DEMO_MODE` lets us skip L0–L4 for one request so judges see the **chain itself** revert a 19.5% APR draw
and an over-limit draw, each with its own tx hash.

What binds a fully stolen agent key (be precise if judges ask): contract and function allowlist, payee bound at
registration, approved limit, advance vs on-chain face value, per-tx and daily caps, expiry, pause, duplicate and
already-drawn checks. The APR the agent reports is also capped by the risk-oracle's approval, so lying about it takes
two keys.

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

`eval/cases.jsonl` holds 49 cases: 39 attacks (A1–A6 from the architecture, Finance's V5 and V8, payee swaps incl. a
homoglyph, tampered and stale decisions, injections in English, Thai, Chinese, base64 and zero-width form, canary
leak, replay, schema abuse, privilege attempts, two agent-loop cases) and 10 benign cases (happy paths, the large
invoice that should wait for approval, settlement incl. dilution, late and short pay, benign text that mentions
payments). `eval/run_eval.py` reports:

| Metric | Target |
|---|---|
| Unauthorized payments (attack success rate) | **0%** |
| Attacks caught (blocked or sent to a human) | 100% |
| Which layer stopped each attack | funnel chart for the slide |
| Injection scanner alone (recall) | reported honestly; below 100% is expected and is the argument for layering |
| Benign cases wrongly blocked | ≤ 10% |
| Benign cases completed | ≥ 90% |

Slide line: *"We attacked our own agent 39 ways. The scanner alone caught X%; the full stack let zero unauthorized
payments through, and the APR and over-limit attempts have on-chain revert hashes."*

## 6. Interfaces (details in the service CLAUDE.md §6)

`POST /wallet/register`, `/wallet/approve`, `/wallet/execute`, `/wallet/settle`, `/wallet/mandate/activate`,
`/wallet/confirm/{tx_id}` (human approval), `/wallet/pause|unpause`, `GET /wallet/audit/{invoice_id}`, `/health`.
Tx result: `tx_id, status (executed | blocked | pending_approval | failed), chain, chain_ref, approvals_required,
block_reason, audit_ref`. Mock hashes are prefixed `mock:` so nobody mistakes them for chain hashes.

## 7. Open items for P

1. **Token:** tTHB (default, matches Finance's THB scenario) or mock USDC. Only names, decimals and amounts change.
2. **Contract PR to `shared/schemas.py`:** add the wallet models from architecture §5.3 and `TxStatus` values
   `blocked`, `failed` (the skeleton still has `rejected`). The wallet returns `rejected` until then.
3. **Env defaults:** `WALLET_MAX_TX_AMOUNT=10000` and `WALLET_HUMAN_APPROVAL_OVER=5000` in `.env.example` would block
   the THB 524,300 demo draw; suggest `1000000` and `837500`.
4. **Human-approval endpoint name:** `POST /wallet/confirm/{tx_id}`, because `/wallet/approve` is the TX‑2 credit
   approval in the architecture.
5. **Revert style:** string reverts (`require(…, "AprAboveMandate")`) instead of custom errors, so FISCO receipts and
   console screenshots show readable reasons. Same names as the architecture.
6. **Freeze time:** scope says Sun 12:00, architecture says 18:00.

## 8. Status (engineer updates)

| Item | Status |
|---|---|
| Contracts + Foundry tests | _not started_ |
| Mock ledger + endpoints | _not started_ |
| FISCO chain + deploy | _not started_ |
| Guard L0–L4 | _not started_ |
| Eval: ASR / catch rate / scanner recall | _— / — / —_ |
| Demo tx hashes (TX‑1…TX‑5, 2 reverts, anchor) | _0 / 8_ |
