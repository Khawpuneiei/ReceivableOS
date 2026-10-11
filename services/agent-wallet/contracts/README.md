# contracts

Solidity for FISCO BCOS, compiled with solc **0.8.11** (CLAUDE.md 5.6). Owner: Agent AI engineer.

Status: the five contracts compile, and `forge test` passes 23 tests. **Not yet deployed.** The FISCO node,
`scripts/deploy.py` and the console screenshots come next. `deployments.json` is written by the deploy script.

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
| `PolicyGuard` | The on-chain mandate: allowed (target, selector) pairs, per-tx cap, rolling 24h cap, APR ceiling, expiry, human-review threshold, payee allowlist. |
| `ReceivableRegistry` | Receivables keyed by the keyed invoice fingerprint. Binds the seller at registration. Records the risk oracle's approval. |
| `FinancingVault` | Lender deposits, draws, and the settlement waterfall. Holds discount fees for lenders to claim. |
| `AgentWallet` | The agent's only entry point. Runs `PolicyGuard`, then calls the target or holds the call for the approver. |

## Roles

| Role | Holder | Can |
|---|---|---|
| owner | P (PM) | Set the mandate, the allowlists, and the wiring (once). Unpause the wallet. Set the settlement payer. |
| agent | Wallet service | `AgentWallet.execute` and `anchorAudit` only. |
| approver | Finance teammate | `AgentWallet.confirm` (release or decline a held payment). Pause. |
| riskOracle | Separate key | `ReceivableRegistry.approve` (TX-2). |
| lender | Setup script | `FinancingVault.deposit`, `claimFees`. |

The owner cannot confirm payments, and the approver cannot change the mandate.

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

## Events

`DecisionExecuted`, `ApprovalRequired`, `ApprovalConfirmed`, `ApprovalDeclined`, `Paused`, `Unpaused`,
`AuditAnchored` (wallet); `ReceivableRegistered`, `ReceivableApproved`, `StatusChanged` (registry);
`Deposited`, `Drawn`, `Settled`, `FeesClaimed` (vault); `MandateSet`, `CallSet`, `PayeeSet` (guard).

## Wiring order

1. Deploy `MockStable`, `PolicyGuard`, `ReceivableRegistry(riskOracle)`, `FinancingVault(token, platform)`, `AgentWallet(agent, approver, guard)`.
2. `guard.wire(wallet)`, `registry.wire(wallet, vault, guard)`, `vault.wire(wallet, registry, guard)`. Each is one-time.
3. `vault.setSettlementPayer(buyer)`.
4. `guard.setMandate(...)`, `guard.setCall(registry, register)`, `guard.setCall(vault, draw)`, `guard.setCall(vault, repay)`, and `guard.setPayee(...)` for the seller, lenders, and platform.

## Differences from the Python mock (CLAUDE.md 5.6)

- **No payee argument on `draw`.** The vault always pays the seller bound at registration. A compromised agent cannot redirect a payment by changing calldata.
- **Settlement is sent with amount 0.** A repayment is not counted against the tx or daily caps. The mock does the same.
- **Settlement payer is one account**, set by the owner. The demo has one buyer.
- **Lender discount fees stay in the vault** and are claimed with `claimFees()`. They are not sent at draw.
- **`AdvanceAboveMandate` is checked in the vault**, after the approved limit, so the order matches the mock. The mock reports `AmountAboveLimit` for an 80% advance when the approved limit is also below the amount. The off-chain layer reports `AdvanceAboveMandate` for the same case.
- **The daily cap is charged once.** A held draw counts when proposed, and `confirm` does not count it again. This matches the fixed mock.
- **Rolling 24h window** on-chain, with the same boundary as the mock (entries at or after now minus one day).

## Still to do

- `scripts/deploy.py`: deploy, wire, write `deployments.json`, and print every tx hash with its receipt.
- FISCO deployment and call screenshots (console or python-sdk), required by the 2024 FinTechathon rules.
- Foundry tests for the settlement and the fee claim are covered; the deployed-address checks are not yet written.
