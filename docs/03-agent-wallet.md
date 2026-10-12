# 03 · Agent Wallet and Agent Guardrails

> **Who this is for:** P (PM) and anyone who needs the wallet in one read. The Agent AI engineer keeps the
> **Status** table at the bottom current. The full build brief, contract specs and ready-to-paste prompts are in
> [`services/agent-wallet/CLAUDE.md`](../services/agent-wallet/CLAUDE.md). The attack test sets are in
> [`services/agent-wallet/eval/`](../services/agent-wallet/eval/), the on-chain record is in
> [`eval/fisco-deployment.md`](../services/agent-wallet/eval/fisco-deployment.md), and the security inputs for the PM's
> assessment are in [`security-self-assessment-inputs.md`](../services/agent-wallet/docs/security-self-assessment-inputs.md).
>
> Last updated 11 Oct 2026: the contracts run on a FISCO BCOS 3.16.4 chain, and the demo's on-chain transactions are
> checked against it.

## 1. What the agent wallet is

The only component in ReceivableOS that holds keys and moves money. It turns a credit decision into on-chain money
movements (register the invoice, record the approval, draw the advance, settle when the buyer pays), but only inside
a **mandate** the SME set and the agent cannot change. It also owns all Solidity: `MockStable` (tTHB),
`ReceivableRegistry`, `FinancingVault`, `PolicyGuard`, `AgentWallet`. They are deployed on a local FISCO BCOS chain
and on Anvil. The mock ledger runs the same rules without a node.

One sentence for the pitch: **the AI proposes, deterministic code and the mandate decide, the contracts enforce,
and a human approves anything large, so a hijacked or wrong AI produces a red "BLOCKED" row, not a payment.**

## 2. How a financing flows through it (demo numbers from `docs/02`)

| Tx | Call | Who signs | What it proves |
|---|---|---|---|
| setup | deploy, `PolicyGuard.setMandate` | owner (P) | the mandate is on-chain: 70% max advance, 12% max APR, 5% max PD, per-tx cap 1.5m, daily cap 3m, human review at or above THB 837,500 |
| TX‑3 | `Vault.deposit` | the deploy script (a stand-in for lenders) | lender liquidity is in the vault |
| TX‑1 | `Registry.register(fingerprint, docHash, seller, 749000, dueDate)` | agent via `AgentWallet` | the keyed invoice fingerprint from OCR is unique, so a re-saved PDF of the same invoice still reverts; the seller's payout address is bound now, from the payee registry, never from invoice text |
| TX‑2 | `Registry.approve(fingerprint, 524300, 1095 bps, decisionHash)` | risk-oracle key | policy-ai's exact decision (by hash) approved this limit, at the APR its fee implies (0.009 per 30 days is 10.95%) |
| TX‑4 | `AgentWallet.execute → PolicyGuard.check → Vault.draw` | agent | draw 524,300 from Lender A (10.95% APR beats B's 65% advance); seller gets 516,705.14 after fees |
| TX‑5 | `AgentWallet.execute → Vault.repay` | agent | buyer paid 749,000: lender 524,300, seller reserve 224,700 |
| anchor | `AgentWallet.anchorAudit(root)` | agent | the off-chain audit log can't be rewritten later |

## 3. The six layers between an AI and the money

| Layer | Where | Stops |
|---|---|---|
| L0 Schema | wallet service | malformed or non-positive amounts, more than two decimals, unsupported currency, the demo bypass outside demo mode |
| L1 Provenance | wallet service | at approval: the decision is not `approve`, its hash does not recompute, or the limit and fee differ from the decision's. At the draw: the decision is stale, or its hash differs from the one approved on chain |
| L2 Injection scan | wallet service | instructions in any text field: rules (zero-width characters, look-alike letters, base64, and some Thai and Chinese phrasings), a canary, and an optional classifier. The classifier is the English-only ProtectAI DeBERTa model, not Llama Prompt Guard 2, and is audit-only by default |
| L3 Mandate & spending | wallet service | a seller not verified in the payee registry (KYC), a mandate not yet valid or expired, a request that names another mandate, APR above the mandate or the approved APR, advance vs face value, PD, per-tx and rolling 24h caps, payee and target allowlist, duplicate, already drawn, approved limit, pause |
| L4 Human approval | wallet service + `AgentWallet.confirm` | anything at or above THB 837,500 waits for the approver (the Finance teammate; P sets the rules and can't approve payments) |
| L5 On-chain guard | `PolicyGuard`, `Vault`, `Registry` | the money limits again: payee allowlist (KYC-verified payees only), amount, limit, advance, APR, caps, expiry, pause, duplicate, already drawn. PD, mandate ID, currency and the KYC check itself are off-chain only |

On stage, `DEMO_MODE` lets us skip the off-chain guard checks for one request, so judges see the **chain itself** revert
a 19.5% APR draw and an over-limit draw, each with its own tx hash. The money format check still applies.

What binds a fully stolen agent key (be precise if judges ask): contract and function allowlist, payee bound at
registration, approved limit, advance vs on-chain face value, per-tx and daily caps, expiry, pause, duplicate and
already-drawn checks. The APR the agent reports is also capped by the risk-oracle's approval, so lying about it takes
two keys. The agent endpoints also need the agent token, which is a separate credential from the risk oracle's.

**Known limit for the pitch:** the risk-oracle key that signs TX‑2 still sits in the wallet's environment in the MVP, so
the wallet could in principle approve its own receivable. What is in place: `/wallet/approve` needs the risk-oracle
token, and the approval must carry the decision it names (its hash, limit and fee are checked). The production answer
is policy-ai's own signer or an HSM.

**Known limits, to state rather than hide:**
- The decision is checked by hash, not signed, so whoever holds the risk-oracle token can approve a decision of their own.
- PD is checked off-chain only. With the guard bypassed, a draw above the PD ceiling executes (v5 cases S15 and S16).
- A draw is refused with `FeesExceedAmount` when the lender's and platform's fees together reach the draw amount. On the
  demo invoice, any draw under about THB 2,270 is refused.
- The FISCO chain is four nodes on one machine, in a Docker container. It shows the contracts and calls work on FISCO
  BCOS; it is not a multi-party network.
- KYC is a mock flag in the payee registry, not a KYC provider.

## 4. Threats and the defenses we use

Threats: prompt injection through invoice text (A1), payee substitution ("our account changed"), instructions
smuggled in other services' outputs, tool misuse (agent tries to unpause or loosen its own mandate), oversized or
off-mandate payments (A3, A4, V5, V8), replay and double financing (A2), data exfiltration, decision tampering,
stolen agent key, obfuscated injections, expired mandate or paused wallet (A6).

State of the art we build on (2024–26): OWASP Top 10 for LLM apps (prompt injection, excessive agency), Google
DeepMind's CaMeL and the "design patterns for securing LLM agents" paper (plan-then-execute, quarantined LLM,
provenance of values), Microsoft's spotlighting, OpenAI's instruction hierarchy, Meta's Prompt Guard 2 and
LlamaFirewall (we do not use these yet), canary tokens, human-in-the-loop for money, smart-account guards (Safe,
ERC‑4337 ideas) and the AgentDojo way of measuring attack success. The shared lesson: **detectors miss things, so design
the system so a fully hijacked model still cannot move money**, and use detectors to catch attacks early and explain them.

Our concrete version: the LLM that reads invoices has no tools; payees only ever come from the registry and are
bound on-chain at TX‑1, so a value that came from untrusted text can never reach a payment; the agent key can call
one function; every limit is checked twice (Python and chain).

## 5. Attack test sets and the numbers for the pitch

The seed set `eval/cases.jsonl` has 51 entries: 40 marked as attacks (two agent-loop cases are skipped, so 38 run) and
11 benign. The other sets are `dev_cases.jsonl`, `heldout_cases.jsonl` (v1), `heldout_v2_cases.jsonl`,
`heldout_v3_cases.jsonl`, `heldout_v4_cases.jsonl`, and `heldout_v5_cases.jsonl`, which tests the structural layers.

| Set | Attacks | Caught (guard on) | Unauthorized, §7.4 (guard on) | Reached execute (guard on) | Benign blocked | Status |
|---|---|---|---|---|---|---|
| Seed (`cases.jsonl`) | 38 | 38/38 | 0/38 | 0/38 | 0/11 | Written with the rules; a regression set |
| Dev | 36 | 36/36 | 0/36 | 0/36 | 0/18 | Used for tuning |
| Held-out v1 | 30 | 30/30 | 0/30 | 0/30 | 0/10 | Tuned on after its first run; contaminated |
| Held-out v2 | 30 | 28/30 | 0/30 | 2/30 | 0/10 | V25 is malformed (hand-encoded ROT13 decodes to nonsense) |
| Held-out v3 | 24 | 14/24 | 0/24 | 10/24 | 1/10 | First clean run, rules frozen before it |
| Held-out v4 | 30 | 12/30 | 0/30 | 18/30 | 0/14 | Second clean run; rules unchanged since v3 |
| Held-out v5 (structural) | 24 | 24/24 | 0/24 | 0/24 | 1/10 | Tests the structural layers through text attacks. Not a detection test |

"Reached execute" counts attacks whose draw moved money. A draw inside the mandate is not unauthorized under §7.4, so
it is not counted there. On held-out v3 and v4, these are the attacks the detectors missed; the limits still held.

The unauthorized-payment number follows CLAUDE.md §7.4: tTHB moved to a non-allowlisted address, above a cap, outside
the mandate, or twice. The runner checks the mock ledger's record after each case, not the guard's verdict. An attack
whose text was accepted but whose draw stayed inside the mandate is not unauthorized. The number "attacks that reached
execute" is reported separately.

Chain only (`--skip-offchain`, the on-chain layer alone): seed 1 of 38 unauthorized (W07, a draw above the PD ceiling),
v4 0 of 30, v5 2 of 24 (S15 and S16, also PD). Those two cases are the reason PD is on the known-limits list.

Scanner recall on its own is lower than the full stack, as expected. On v4, the rules alone caught 10 of 27 injection
and exfiltration cases. That is the argument for layering, and it is reported as it is.

Metrics the runner reports:

| Metric | Target |
|---|---|
| Unauthorized payments (§7.4) | **0%** |
| Attacks caught (blocked or sent to a human) | 100% |
| Which layer stopped each attack | funnel chart for the slide |
| Injection scanner alone (recall) | reported honestly; below 100% is expected and is the argument for layering |
| Benign cases wrongly blocked | ≤ 10% |
| Benign cases completed | ≥ 90% |

Slide line: *"We attacked our own agent with a seed set of 38 attacks and held-out sets of 24 to 30 attacks each. The scanner
alone caught 14 of 24 and 12 of 30 held-out attacks. With the full stack, no held-out attack moved money outside the
mandate. The same draws were run on a 4-node FISCO BCOS chain: the APR and over-limit attempts revert on chain with
their own transaction hashes, and every hash is checked against the chain."*

## 6. Interfaces (details in the service CLAUDE.md §6)

`POST /wallet/register`, `/wallet/execute`, `/wallet/settle` (`X-Agent-Token`), `POST /wallet/approve`
(`X-Risk-Oracle-Token`, and the decision it names), `/wallet/mandate/activate` (owner token), `/wallet/confirm/{tx_id}`
(human approval, approver token only), `/wallet/pause|unpause`, `GET /wallet/audit/{invoice_id}`, `/health`.
Tx result: `tx_id, status (executed | blocked | pending_approval | failed), chain, chain_ref, approvals_required,
block_reason, audit_ref`. On the mock, hashes are prefixed `mock:` so nobody mistakes them for chain hashes. FISCO
hashes are plain transaction hashes.

The switch is `LEDGER_MODE` (`mock` or `fisco`), as in the scope doc.

## 7. Decisions so far and what's still open

Settled (via the coordinator): tTHB as default token (P may still switch to mock USDC); `blocked`/`failed` statuses are
in `shared/schemas.py`; demo caps THB 1,500,000 per transaction and 3,000,000 daily, human review at or above
837,500, all THB with 2 decimals; `POST /wallet/confirm/{tx_id}` for human approval; readable revert strings;
real FISCO BCOS hashes (mandatory for the submission) land 13–15 Oct, final documents 16–17 Oct, early upload 18 Oct,
final submission 20 Oct 22:59 Bangkok; Base Sepolia deploy of the same contracts is an optional extra for the on-chain
bonus points; mandate fields `max_ltv`, `max_apr`, `max_predicted_default`, `human_review_above`, `max_amount_per_tx`,
`daily_cap` (policy-ai's shape); `risk_score` is the buyer PD; registry dedupes on the keyed `invoice_fingerprint` from OCR.

Code freeze: the scope doc says **12 Oct 12:00** Bangkok. Its weekday label, "Sunday", does not match 12 Oct 2026, which
is a Monday. The labels in the scope timeline follow the 2025 calendar. P to confirm the date.

Decided by the Agent AI engineer, to be confirmed by P:
- `LEDGER_MODE`, not `CHAIN_MODE`, to match the scope doc. Done.
- KYC: a mock flag per payee. Unverified sellers are refused at registration and not allowlisted on chain. Done.
- An agent token on register, execute and settle. Done.
- PD stays off-chain. The contract change would need the risk score in `execute`; it is not in the MVP.
- Decision signing is not built. It needs a `contract:` PR to `PolicyDecision`.
- A draw that the fee rule refuses (under about THB 2,270 on the demo invoice) stays refused. The alternatives are taking the
  fee from settlement or a minimum draw in the mandate.

Still open for P:
- Final tTHB vs USDC.
- Who holds the approver key (default: the Finance teammate).
- Whether to separate the risk-oracle key from the wallet process (the token gate is in; the key is still co-located).
- Whether to spend 18–20 Oct on the Base Sepolia bonus deploy.
- Whether PD is enforced on-chain (a `PolicyGuard` change, and the risk score would go into `execute`).
- Whether decisions are signed (a `contract:` PR to `PolicyDecision`).

## 8. Status (engineer updates)

| Item | Status |
|---|---|
| Contracts + Foundry tests | Five contracts, solc 0.8.11. 42 Foundry tests pass (40 revert, settlement and flow tests, and 2 time-unit tests). Every revert string has a test. The guard's time unit is set per chain (`timeScale`) |
| FISCO chain | **Running.** A 4-node Air chain, FISCO BCOS 3.16.4, in a Docker container, chain0 and group0 |
| FISCO deploy | **Done.** 22 deploy transactions on chain, each checked against it (`eval/fisco-deployment.md`, `eval/fisco-verification-deploy.txt`) |
| FISCO adapter and demo | **Done.** The wallet runs with `LEDGER_MODE=fisco`. The demo's 8 sections give the same outcomes as on the mock. Its 11 record hashes are on chain: 8 succeed, 3 revert with `AmountAboveLimit`, `AprAboveMandate`, `DuplicateReceivable` (`eval/demo_tx_hashes_fisco.md`, `eval/fisco-verification-demo.txt`) |
| FISCO bug found and fixed | FISCO reports `block.timestamp` in milliseconds. The first FISCO deploy treated it as seconds, so every mandate looked expired. Fixed with `PolicyGuard.timeScale`. Anvil could not show this, because it uses seconds |
| Mock ledger + endpoints | Done: register, approve, execute, settle, confirm, pause, mandate, audit, holds. 137 pytest tests pass (2 skipped: the classifier model tests). Agent token on register, execute and settle; risk-oracle token on approve |
| Guard L0–L4 | Done for draws: L0–L4 checks, hold-for-approval, hash-chained audit log, anchoring at settlement. KYC flag enforced off-chain and on chain (allowlist). The off-chain check also refuses a seller whose `kyc_expiry` has passed. PD, mandate ID and currency are off-chain only |
| Eval | Seed set (guard on): 38/38 caught, 0/38 unauthorized, 0/11 benign blocked. Held-out v3: 14/24 caught, 10 reached execute. Held-out v4: 12/30 caught, 18 reached execute. None of them unauthorized under §7.4. Structural set v5: 24/24. The classifier is audit-only by default |
| Anvil | `scripts/deploy.py` and `scripts/evm_smoke.py`: 7 of 7 checks pass after the time-unit change |
| Clean-clone run | Run at `fedd575` from the README's steps: `pytest` 135 passed, 2 skipped; mock demo exit 0. Run by an AI, not a teammate. Submission item 4 needs a teammate to do this. On Windows, clone to a short path: the receipt filenames break the 260-character limit under a long one |
| Daily cap across restarts | On FISCO, startup seeds the off-chain 24h cap from `PolicyGuard.rollingSpend()`. A failed read stops the wallet from starting. Read live on 11 Oct: THB 1,504,300.00 |
| Demo lender | Selected from `data/agent/lender_quotes.json`: the highest advance inside the mandate's APR cap. Not hardcoded |
| FISCO rehearsal | `fisco_demo.sh --fresh`, run `20261011122302`: 22 of 22 deploy hashes and 11 of 11 demo hashes on chain. `eval/fisco-deployment.md` is written from the receipts |
| Demo data | `data/agent/` is tracked. The root `.gitignore` rule `data/*` had hidden it; P to add `!data/agent/` |
| Config name | `LEDGER_MODE` (matches the scope doc) |
| Console screenshots | Not produced. The verification output and the receipts are the evidence in the repo |
| Security self-assessment inputs | Written: `services/agent-wallet/docs/security-self-assessment-inputs.md`. Checked against `docs/06` on 12 Oct: the mandate values match §1.4. The §6 checklist gaps are known risks 15 to 17 (holds in memory, outstanding exposure, `flow_id`). KYC credentials can now expire (risk 13) |
