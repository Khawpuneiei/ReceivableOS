# contracts

Solidity contracts for FISCO BCOS. Deployed addresses go in `deployments.json` here.

| Contract | Purpose | Owner (default, see docs/00-scope.md) |
|---|---|---|
| `ReceivableRegistry` | Register invoice fingerprints, reject duplicates | PM |
| `FinancingVault` | Fund, draw, repay, settle | PM |
| `MockStable` | Demo stable token | PM |
| `AgentWallet` | Agent's on-chain wallet | Agent AI engineer |
| `PolicyGuard` | Enforces the mandate on chain; reverts out-of-policy calls | Agent AI engineer |

Each owner edits only their own `.sol` files. Shared interfaces between contracts change by a separate PR, like the API contract.

Every chain call from Python goes through an interface with a mock implementation, selected by `CHAIN_MODE=mock|fisco`, so the demo runs without a node.
