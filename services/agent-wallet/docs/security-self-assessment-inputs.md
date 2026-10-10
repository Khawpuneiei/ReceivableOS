# Security self-assessment: inputs from the agent wallet

For the PM, who writes `pitch/security-self-assessment.md` from these inputs (CLAUDE.md §12). Every number here comes
from a run in this repo, and the commit it was measured at is noted. Where a result is contaminated or partial, it says so.

## 1. Permission tiers

| Key | Holder | Can call | Cannot call | Enforced by |
|---|---|---|---|---|
| owner | P (PM) | `PolicyGuard.setMandate`, `setCall`, `setPayee`, `wire` (once), `setSettlementPayer`, `AgentWallet.unpause` | `confirm` (payments) | `onlyOwner`; `testOwnerCannotConfirmAPayment` |
| agent | wallet service | `AgentWallet.execute`, `anchorAudit` | `approve`, `confirm`, `unpause` | `onlyAgent`; `testOnlyTheAgentCanExecute` |
| approver | Finance teammate | `AgentWallet.confirm`, `pause` | `setMandate` | `onlyApprover`; `testOwnerCannotConfirmAPayment` |
| riskOracle | separate key | `ReceivableRegistry.approve` (TX-2) | `register`, `draw` | `onlyRiskOracle` |
| lender | setup script | `FinancingVault.deposit`, `claimFees` | `draw`, `repay` | the vault only accepts draws from the wallet |

Off-chain (HTTP), the owner and approver endpoints check tokens (`X-Owner-Token`, `X-Approver-Token`). **The agent
endpoints do not** (see the risks, §5).

## 2. Controls

Off-chain guard, in layer order (`app/guard/pipeline.py`, `app/guard/injection.py`):

- **L0:** schema, currency, and amount precision.
- **L1:** the decision must be `approve`, its hash must match the one approved on chain, and it must be fresh (`valid_until`,
  a wallet-side stopgap).
- **L2:** injection rules across decoded views, the canary, and an optional classifier (`log`, `hold`, or `block`).
- **L3:** payee bound to the seller, target allowlist, mandate expiry, pause, per-tx and rolling 24h caps, APR ceiling,
  advance against face value, approved limit, and already drawn.
- **L4:** amounts at or above THB 837,500.00 (inclusive) need an approver. Holds expire after 24 hours.
- **L5:** the same checks in the contracts (`contracts/src/*.sol`), with the same revert strings.

Other controls:
- Idempotency keys on every write, so a retry cannot pay twice.
- The DEMO bypass (`skip_offchain_checks`) is refused unless `DEMO_MODE=1`, and every use is recorded.
- Hash-chained audit log: a change to any entry makes `verified` false. The head is anchored on chain at settlement.
- Canary token: the injection path's canary leak is reported before generic injection.

## 3. Measured results

Commit `48540f0` (docs), code at `ba2278d`. Run with `services/agent-wallet/eval/run_eval.py`.

| Set | Cases | Attacks | Caught (guard on) | Benign blocked | Notes |
|---|---|---|---|---|---|
| Seed (`cases.jsonl`) | 49 (2 agent-loop skipped) | 38 | 38/38, ASR 0/38 | 0/11 | Written with the rules; treat as a regression set |
| Dev | 54 | 36 | 36/36 | 0/18 | Used for tuning. Not a generalisation estimate |
| Held-out v1 | 40 | 30 | 30/30 | 0/10 | Tuned on after its first run. Contaminated |
| Held-out v2 | 40 | 30 | 28/30 (rules); 29/30 (with classifier) | 0/10; 1/10 with classifier blocking | V25 is malformed (hand-encoded ROT13 decodes to nonsense) |
| **Held-out v3** | 34 | 24 | **14/24 (rules, frozen before the run)**; 17/24 with classifier blocking | 1/10 rules; 2/10 classifier blocking | The first clean run. Misses: directives with no override verb, and zh/ja/th/es phrasings |

Guard off (chain only, `--skip-offchain`): 11 of 38 seed attacks execute. These are text, decision-semantics, PD, and
currency attacks, which only the off-chain layers can see. The on-chain layer enforces the money invariants.

Chain check on Anvil (`scripts/evm_smoke.py`, Solidity contracts, not the mock): 7/7 checks pass. The on-chain balances
match the Python mock's numbers, and `AprAboveMandate` and `AlreadyDrawn` are refused on-chain.

Clean-clone demo: a fresh clone, a fresh virtual environment, run twice. The transcripts are identical.

## 4. Test evidence

- `pytest services/agent-wallet`: 102 passed, 2 skipped (the model tests need `INJECTION_MODEL_DIR`).
- `forge test --offline` in `contracts/`: 23 passed.
- `ruff check`: clean.

## 5. Known risks (please read before writing the assessment)

1. **HIGH: the agent-facing HTTP endpoints have no authentication.** `/wallet/execute`, `/wallet/register`,
   `/wallet/approve`, and `/wallet/settle` accept any caller. Anyone who can reach port 8003 can perform the agent's
   actions, including approving a credit limit. The mock ledger's `approve` does not check the caller either.
   On-chain, `approve` is restricted to the risk oracle key, and the Solidity path refuses other callers. Before any
   deployment: keep the service on a private network, and add separate agent and risk-oracle tokens, which changes the
   orchestrator's requests. Decision needed from the PM.
2. **The risk oracle key is co-located with the wallet in the MVP** (CLAUDE.md §5.1). The production answer is the
   policy service's own signer or an HSM.
3. **Single approver.** The Finance teammate is the only one who can release a payment. There is no M-of-N.
4. **No key management yet.** The mock has no keys. The Anvil path uses unlocked accounts and is refused on any other
   chain id. FISCO key handling is not designed yet. CLAUDE.md §5.1 specifies key files outside git.
5. **Detector recall is partial.** On the clean held-out set, rules catch 14 of 24 attacks. The classifier is English-only,
   does not detect jailbreaks, and is audit-only by default. Blocking mode raises benign false blocks, so it is not enabled.
6. **Decision freshness** uses a wallet-side `valid_until` stopgap. The 15-minute approval-age rule from CLAUDE.md §5.4
   is not implemented.
7. **Settlement payer is one account** in the demo. A production system needs the actual buyer's authorisation.
8. **V8 mismatch.** For an 80% advance against an approved limit that is also below the amount, the on-chain layer reports
   `AmountAboveLimit` and the off-chain layer reports `AdvanceAboveMandate`. The outcome is the same: the draw is refused.
9. **No full eval on the EVM.** The Anvil check covers the happy path and two refusals. The full red-team set runs
   against the mock only.

## 6. What still needs an answer from the PM

- Risk 1: how the agent and risk-oracle endpoints are authenticated, and whether the orchestrator can send the tokens.
- Who holds the approver token and the owner token in each environment.
- Whether the FISCO deployment keys live in key files or an HSM (CLAUDE.md §5.1 says files).
