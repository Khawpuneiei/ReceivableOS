# contracts

Solidity for FISCO BCOS, compiled with solc **0.8.11** (CLAUDE.md 5.6). Owner: Agent AI engineer.

Status:
- **FISCO BCOS 3.16.4**, a 4-node Air chain (chain0, group0). The five contracts are deployed and wired, and every
  deploy transaction is on chain. The record is in [`eval/fisco-deployment.md`](../eval/fisco-deployment.md), with the
  receipts in [`eval/fisco-receipts/`](../eval/fisco-receipts/). The addresses are in `deployments.json` under `fisco`.
- **Local Anvil** (chain 31337): the same contracts, with `scripts/evm_smoke.py` passing 7 of 7 checks.
- `forge test --offline` passes 25 tests (23 revert and settlement tests, and 2 time-unit tests).

## Build and test

Forge needs the compiler binary. Set `FOUNDRY_SOLC` to the path of `solc-0.8.11` on your machine, then run from
this folder. Nothing is downloaded during the build.

```bash
export FOUNDRY_SOLC=/path/to/solc-0.8.11
forge build --offline
forge test --offline
```

The tests do not use `forge-std`. They call the standard Foundry cheat-code address directly.

## Contracts

| Contract | Purpose |
|---|---|
| `MockStable` | tTHB, 2 decimals. Demo token; the owner mints. |
| `PolicyGuard` | The on-chain mandate: allowed (target, selector) pairs, per-tx cap, rolling 24h cap, APR ceiling, expiry, human-review threshold, payee allowlist. Takes the chain's time unit at deploy (see below). |
| `ReceivableRegistry` | Receivables keyed by the keyed invoice fingerprint. Binds the seller at registration. Records the risk oracle's approval. |
| `FinancingVault` | Lender deposits, draws, and the settlement waterfall. Holds discount fees for lenders to claim. |
| `AgentWallet` | The agent's only entry point. Runs `PolicyGuard`, then calls the target or holds the call for the approver. |

The deployed addresses for each chain are in `deployments.json`. The FISCO block is the one the wallet uses.

## Roles

| Role | Holder | Can |
|---|---|---|
| owner | P (PM) | Set the mandate, the allowlists, and the wiring (once). Unpause the wallet. Set the settlement payer. |
| agent | Wallet service | `AgentWallet.execute` and `anchorAudit` only. |
| approver | Finance teammate | `AgentWallet.confirm` (release or decline a held payment). Pause. |
| riskOracle | Separate key | `ReceivableRegistry.approve` (TX-2). |
| lender | Setup script | `FinancingVault.deposit`, `claimFees`. |

The owner cannot confirm payments, and the approver cannot change the mandate. On the demo deployment, the owner,
agent, approver, and risk oracle keys are separate accounts, but the wallet service holds all of them in the MVP.

## Key functions and revert strings

Strings match the Python mock, so the same attack gives the same reason on both sides.

| Function | Reverts |
|---|---|
| `AgentWallet.execute` | `Paused`, `NotAgent`, `SchemaInvalid`, then the guard and vault reasons below |
| `PolicyGuard.check` / `revalidate` | `TargetNotAllowed`, `MandateExpired`, `AmountAboveTxCap`, `DailyCapExceeded` (check only), `AprAboveMandate` |
| `ReceivableRegistry.register` | `PayeeNotAllowed`, `DuplicateReceivable`, `NotWallet` |
| `ReceivableRegistry.approve` | `NotRiskOracle`, `NotRegistered`, `AlreadyApproved` |
| `FinancingVault.draw` | `NotRegistered`, `AlreadyDrawn`, `NotApproved`, `AprAboveMandate`, `AmountAboveLimit`, `AdvanceAboveMandate`, `FeesExceedAmount`, `InsufficientLiquidity` |
| `FinancingVault.repay` | `AlreadySettled`, `NotDrawn` |
| `AgentWallet.confirm` | `NotApprover`, `NotPending`, `Paused` |

A target's revert reason is passed through unchanged (`AgentWallet._call`), so the string reaches the caller.
`KycNotVerified` and `PdAboveMandate` are checked off-chain only (see the differences below).

## Events

`DecisionExecuted`, `ApprovalRequired`, `ApprovalConfirmed`, `ApprovalDeclined`, `Paused`, `Unpaused`,
`AuditAnchored` (wallet); `ReceivableRegistered`, `ReceivableApproved`, `StatusChanged` (registry);
`Deposited`, `Drawn`, `Settled`, `FeesClaimed` (vault); `MandateSet`, `CallSet`, `PayeeSet` (guard).

## Wiring order

1. Deploy `MockStable`, `PolicyGuard(timeScale)`, `ReceivableRegistry(riskOracle)`, `FinancingVault(token, platform)`,
   `AgentWallet(agent, approver, guard)`.
2. `guard.wire(wallet)`, `registry.wire(wallet, vault, guard)`, `vault.wire(wallet, registry, guard)`. Each is one-time.
3. `vault.setSettlementPayer(buyer)`.
4. `guard.setMandate(...)`, `guard.setCall(registry, register)`, `guard.setCall(vault, draw)`, `guard.setCall(vault, repay)`,
   and `guard.setPayee(...)` for each KYC-verified party: the seller, the lenders, and the platform.

`scripts/deploy.py` (Anvil) and `scripts/deploy_fisco.py` (FISCO) run these steps and write their addresses to
`deployments.json`. The FISCO script also saves every receipt to `eval/fisco-receipts/`.

## FISCO time unit

FISCO BCOS reports `block.timestamp` in **milliseconds**. The EVM reports seconds. The first FISCO deployment treated the
chain's value as seconds, so every mandate looked expired (the expiry was in seconds, the clock in milliseconds), and
the 24h window was 86 seconds. Running on FISCO caught this; the Anvil runs could not, because Anvil uses seconds.

The fix is `PolicyGuard.timeScale`, set at deploy: `1` on the EVM and `1000` on FISCO. Every time value in the guard
is in seconds, so `expiresAt` and the rolling window mean the same moment on both chains. Two tests cover it
(`test/TimeScale.t.sol`). The earlier FISCO deployments are superseded; their hashes are not part of the record.

## Differences from the Python mock (CLAUDE.md 5.6)

- **No payee argument on `draw`.** The vault always pays the seller bound at registration. A compromised agent cannot redirect a payment by changing calldata.
- **Settlement is sent with amount 0.** A repayment is not counted against the tx or daily caps. The mock does the same.
- **Settlement payer is one account**, set by the owner. The demo has one buyer.
- **Lender discount fees stay in the vault** and are claimed with `claimFees()`. They are not sent at draw.
- **`AdvanceAboveMandate` is checked in the vault**, after the approved limit, so the order matches the mock. The mock reports `AmountAboveLimit` for an 80% advance when the approved limit is also below the amount. The off-chain layer reports `AdvanceAboveMandate` for the same case.
- **The daily cap is charged once.** A held draw counts when proposed, and `confirm` does not count it again. This matches the fixed mock.
- **Rolling 24h window** on-chain, with the same boundary as the mock (entries at or after now minus one day).
- **Time is in seconds on every chain** (`timeScale`, above).
- **PD, mandate ID, currency and KYC are not checked on-chain.** The off-chain guard checks them. KYC is enforced on
  chain in one way: only KYC-verified payees are allowlisted with `setPayee`, so an unverified seller cannot be bound.

## Evidence

- `eval/fisco-deployment.md`: the 22 deploy transactions, each checked against the chain with
  `scripts/verify_fisco_hashes.py` (output in `eval/fisco-verification-deploy.txt`).
- `eval/demo_tx_hashes_fisco.md`: the demo's on-chain transactions, checked the same way (output in
  `eval/fisco-verification-demo.txt`). Receipts are in `eval/fisco-receipts-demo/`.
- Console or python-sdk screenshots, which the 2024 rules ask for, are not in the repo. The verification output and
  the receipts are the text evidence for now.
