# Security self-assessment: inputs from the agent wallet

For the PM, who writes `pitch/security-self-assessment.md` from these inputs (CLAUDE.md §12). Every number here comes
from a run in this repo, and the commit it was measured at is noted. Where a result is contaminated or partial, it says so.

## 1. Permission tiers

| Key | Holder | Can call | Cannot call | Enforced by |
|---|---|---|---|---|
| owner | P (PM) | `PolicyGuard.setMandate`, `setCall`, `setPayee`, `wire` (once), `setSettlementPayer`, `AgentWallet.unpause` | `confirm` (payments) | `onlyOwner`; `testOwnerCannotConfirmAPayment` |
| agent | wallet service | `AgentWallet.execute`, `anchorAudit` | `approve`, `confirm`, `unpause` | `onlyAgent`; `testOnlyTheAgentCanExecute` |
| approver | Finance teammate | `AgentWallet.confirm`, `pause` | `setMandate` | `onlyApprover`; `testOwnerCannotConfirmAPayment` |
| riskOracle | separate key; HTTP token `X-Risk-Oracle-Token` in the MVP | `ReceivableRegistry.approve` (TX-2); `POST /wallet/approve` | `register`, `draw` | `onlyRiskOracle`; the token check on `/wallet/approve` |
| lender | setup script | `FinancingVault.deposit`, `claimFees` | `draw`, `repay` | the vault only accepts draws from the wallet |

Off-chain (HTTP), the owner, approver and risk-oracle endpoints check tokens (`X-Owner-Token`, `X-Approver-Token`,
`X-Risk-Oracle-Token`). **The agent endpoints do not** (see the risks, §5).

## 2. Controls

Off-chain guard, in layer order (`app/guard/pipeline.py`, `app/guard/injection.py`, `app/wallet/lifecycle.py`):

- **L0:** schema, currency, and amount precision.
- **L1:** the approval must name an `approve` decision whose hash recomputes, with its limit and fee equal to the
  decision's. The draw's decision must match the hash approved on chain, and the decision must be fresh (`valid_until`,
  a wallet-side stopgap).
- **L2:** injection rules across decoded views, the canary, and an optional classifier (`log`, `hold`, or `block`).
- **L3:** payee bound to the seller, target allowlist, mandate start and expiry, the request names the active mandate,
  pause, per-tx and rolling 24h caps, APR ceiling, PD ceiling, advance against face value, approved limit, and already
  drawn.
- **L4:** amounts at or above THB 837,500.00 (inclusive) need an approver. Holds expire after 24 hours.
- **L5:** the on-chain checks in the contracts (`contracts/src/*.sol`), with the same revert strings. PD is not checked
  on-chain (risk 10).

Other controls:
- Idempotency keys on every write, so a retry cannot pay twice. A draw sent without a key is keyed on its whole body.
- Approval needs the risk-oracle token and the decision it names. Review and reject decisions are refused.
- The DEMO bypass (`skip_offchain_checks`) is refused unless `DEMO_MODE=1`, and every use is recorded.
- Hash-chained audit log: a change to any entry makes `verified` false. The head is anchored on chain at settlement.
- Canary token: the injection path's canary leak is reported before generic injection.

## 3. Measured results

Commit `43831e2` (HEAD). Uncommitted since then: the §7.4 split (`eval/run_eval.py`, `tests/test_eval_metric.py`) and
the PM-review fixes (approval checks, startup bootstrap, default draw key, mandate checks, lazy classifier import, and a
harness fix so the decision hash covers the placeholders it sends). Neither change moved a detection number. Run with
`services/agent-wallet/eval/run_eval.py`.

**Unauthorized payment (CLAUDE.md §7.4):** tTHB moved to a non-allowlisted address, above a cap, outside the mandate, or
twice. The runner checks the mock ledger's record after each case, not the guard's verdict. An attack whose text was
accepted but whose draw stayed inside the mandate is not unauthorized. The earlier "ASR" counted every executed attack;
that number is now shown as "reached execute".

| Set | Cases | Attacks | Caught (guard on) | §7.4 unauthorized (guard on) | Benign blocked | Notes |
|---|---|---|---|---|---|---|
| Seed (`cases.jsonl`) | 49 (2 agent-loop skipped) | 38 | 38/38 | 0/38 | 0/11 | Written with the rules; treat as a regression set |
| Dev | 54 | 36 | 36/36 | 0/36 | 0/18 | Used for tuning. Not a generalisation estimate |
| Held-out v1 | 40 | 30 | 30/30 | 0/30 | 0/10 | Tuned on after its first run. Contaminated |
| Held-out v2 | 40 | 30 | 28/30 (rules); 29/30 (with classifier) | 0/30 | 0/10; 1/10 with classifier blocking | V25 is malformed (hand-encoded ROT13 decodes to nonsense). Two attacks reached execute, neither unauthorized |
| Held-out v3 | 34 | 24 | **14/24 (rules, frozen before the run)**; 17/24 with classifier blocking | 0/24 | 1/10 rules; 2/10 classifier blocking | The first clean run. Misses: directives with no override verb, and zh/ja/th/es phrasings. 10 reached execute, none unauthorized |
| **Held-out v4** | 44 | 30 | **12/30 (rules, frozen before the run)** | **0/30** | 0/14 | Second clean run; rules unchanged since v3. 18 reached execute, each draw inside the mandate. Misses: English directives with no override verb, and phrasings in th, zh, ko, es, fr and vi. Not measured with the classifier |

**Chain only** (`--skip-offchain`, the DEMO bypass, so only the on-chain layer runs), measured on the seed set and on v4:

- Seed: 10 of 38 attacks reach execute, and **1 of 38 is unauthorized: W07, a draw whose risk score is 8%, above the
  mandate's 5% PD ceiling.** Guard on, W07 is blocked at L3. The count went from 11 to 10 after the PM-review fixes:
  W05, a review decision, is now refused at approval even with the draw guard bypassed.
- v4: all 30 attacks reach execute, and none is unauthorized. The attack text changed only the decision's reasons, so
  every draw was the normal one.

PD is checked off-chain only (CLAUDE.md §5.4; risk 10). These chain-only results come from the Python mock, which mirrors
the contracts. The Anvil check below covers the happy path and two refusals, so the full set has not been run against
the Solidity contracts.

Chain check on Anvil (`scripts/evm_smoke.py`, Solidity contracts, not the mock): 7/7 checks pass. The on-chain balances
match the Python mock's numbers, and `AprAboveMandate` and `AlreadyDrawn` are refused on-chain.

Demo: `scripts/demo.py` runs end to end against a plain `uvicorn app.main:app` start, with no seeding step. The mock
mandate and lender liquidity are set at startup.

Clean-clone demo: a fresh clone, a fresh virtual environment, run twice. The transcripts are identical. This was
measured before the PM-review fixes; run it again before the freeze.

## 4. Test evidence

- `pytest services/agent-wallet`: 122 passed, 2 skipped. The two model tests need `INJECTION_MODEL_DIR`. The 10
  eval-metric tests and the 10 PM-review tests are included.
- `forge test --offline` in `contracts/`: 23 passed.
- `ruff check`: clean.

## 5. Known risks (please read before writing the assessment)

1. **HIGH: the agent endpoints have no authentication.** `/wallet/register`, `/wallet/execute` and `/wallet/settle`
   accept any caller, so anyone who can reach port 8003 can run the agent's actions. The guard still limits what a draw
   can do, but the calls themselves are open. `/wallet/approve` now needs `X-Risk-Oracle-Token`, and the approval must
   carry the decision it names (fixed after the PM review). Before any deployment: keep the service on a private
   network, and add an agent token, which changes the orchestrator's requests. Decision needed from the PM.
2. **The risk oracle key is co-located with the wallet in the MVP** (CLAUDE.md §5.1). The wallet's environment holds the
   risk-oracle token too. The production answer is the policy service's own signer or an HSM.
3. **Single approver.** The Finance teammate is the only one who can release a payment. There is no M-of-N.
4. **No key management yet.** The mock has no keys. The Anvil path uses unlocked accounts and is refused on any other
   chain id. FISCO key handling is not designed yet. CLAUDE.md §5.1 specifies key files outside git.
5. **Detector recall is partial.** Rules catch 14 of 24 attacks on held-out v3 and 12 of 30 on held-out v4. The misses
   are English directives with no override verb, and phrasings in several non-English languages. The classifier is
   English-only, does not detect jailbreaks, and is audit-only by default. Blocking mode raises benign false blocks, so
   it is not enabled. The held-out sets are now measured, not tuned on: a rule change must be measured on a new set.
6. **Decision freshness** uses a wallet-side `valid_until` stopgap. The 15-minute approval-age rule from CLAUDE.md §5.4
   is not implemented.
7. **Settlement payer is one account** in the demo. A production system needs the actual buyer's authorisation.
8. **V8 mismatch.** For an 80% advance against an approved limit that is also below the amount, the on-chain layer reports
   `AmountAboveLimit` and the off-chain layer reports `AdvanceAboveMandate`. The outcome is the same: the draw is refused.
9. **No full eval on the EVM.** The Anvil check covers the happy path and two refusals. The full red-team set runs
   against the mock only.
10. **PD is enforced off-chain only.** Neither the mock nor the contracts check the risk score against the mandate's
    `max_predicted_default`. With the guard bypassed, W07 executes: a draw above the 5% PD ceiling. Guard on, it is blocked
    at L3. Options: pass PD into `execute` and check it in `PolicyGuard` (a contract change), or keep the off-chain check
    and say so in the pitch.
11. **The decision is hashed, not signed.** The wallet checks that the decision matches its hash, the approval, and the
    draw. It cannot check who wrote the decision, so whoever holds the risk-oracle token can approve a decision of their
    own. A signature from policy-ai would close that. It needs a signature field in shared `PolicyDecision`, which is a
    `contract:` PR. `REQUIRE_SIGNED_DECISION` was removed because nothing read it.

## 6. What still needs an answer from the PM

- Risk 1: how the agent endpoints (`/wallet/register`, `/wallet/execute`, `/wallet/settle`) are authenticated, and whether
  the orchestrator can send the risk-oracle token and the full decision on every approve.
- Who holds the approver, owner and risk-oracle tokens in each environment.
- Risk 11: whether policy-ai should sign its decisions (a `contract:` PR to `PolicyDecision`).
- Risk 10: whether PD must also be enforced on-chain. That changes the `execute` inputs and `PolicyGuard`, so it is a
  contract change.
- Whether the FISCO deployment keys live in key files or an HSM (CLAUDE.md §5.1 says files).
