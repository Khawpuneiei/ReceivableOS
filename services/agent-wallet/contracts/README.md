# contracts

Solidity contracts for FISCO BCOS. Deployed addresses go in `deployments.json` here.

Owner: Agent AI engineer (the whole on-chain layer).

| Contract | Purpose |
|---|---|
| `ReceivableRegistry` | Register invoice fingerprints, reject duplicates |
| `FinancingVault` | Fund, draw, repay, settle |
| `MockStable` | Demo stable token |
| `AgentWallet` | Agent's on-chain wallet |
| `PolicyGuard` | Enforces the mandate on chain; reverts out-of-policy calls |

Design: `docs/01-architecture.md` and `docs/03-agent-wallet.md`.

Every chain call from Python goes through an interface with a mock implementation, selected by `CHAIN_MODE=mock|fisco`, so the demo runs without a node.
