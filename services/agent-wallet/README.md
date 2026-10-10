# agent-wallet

Owner: Agent AI engineer. The wallet holds the keys and moves tTHB, and it owns all the Solidity
([`contracts/`](contracts/README.md)). Design: [`docs/03-agent-wallet.md`](../../docs/03-agent-wallet.md).
Build brief for the service: [`CLAUDE.md`](CLAUDE.md). Request and response models: [`shared/schemas.py`](../../shared/schemas.py).

## Status

- **Mock ledger:** the money loop runs end to end over HTTP: register, approve, execute, settle. Guard L0–L4,
  the hash-chained audit log, and hold-for-approval work. `scripts/demo.py` passes from a clean clone.
- **Contracts:** five contracts compile with solc 0.8.11. Foundry tests pass. **Not deployed.**
- **FISCO:** not started. There is no FISCO adapter, so `CHAIN_MODE=fisco` is not supported.
- **Orchestrator:** the integration isn't finished. See `docs/orchestrator-integration.md`.

Per-item status is in the table in [`docs/03-agent-wallet.md`](../../docs/03-agent-wallet.md) section 8.

## Run (mock ledger)

From the repo root:

```bash
export WALLET_OWNER_TOKEN=change-me WALLET_APPROVER_TOKEN=change-me-too
python -m uvicorn app.main:app --app-dir services/agent-wallet --port 8003
```

The mock ledger is seeded at startup: the demo mandate is active and both lenders have liquidity. Then, in another shell:

```bash
python services/agent-wallet/scripts/seed_demo.py --url http://127.0.0.1:8003
python services/agent-wallet/scripts/demo.py --url http://127.0.0.1:8003
```

`demo.py` writes `eval/demo_tx_hashes.md`. Every hash in it is a mock hash (prefix `mock:`), not a chain hash.
The on-chain revert steps need the server started with `DEMO_MODE=1`.

## Test

```bash
pytest services/agent-wallet
ruff check services/agent-wallet
cd services/agent-wallet/contracts && FOUNDRY_SOLC=/path/to/solc-0.8.11 forge test --offline
```

The two classifier model tests run only when `INJECTION_MODEL_DIR` points at the pinned model.

The red-team eval: `python services/agent-wallet/eval/run_eval.py` (default cases, mock ledger). Reports are in `eval/report*.md`.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | Service status and ledger mode |
| POST | `/wallet/register` | agent | TX-1: register a receivable, binding its seller |
| POST | `/wallet/approve` | risk oracle (TX-2) | Record the credit approval and the decision hash |
| POST | `/wallet/execute` | agent | TX-4: guard, then draw; may return `pending_approval` or a held draft |
| POST | `/wallet/settle` | agent | TX-5: settle after the buyer pays |
| GET | `/wallet/holds` | approver token | Open held drafts (ids, amounts, codes; no invoice text) |
| POST | `/wallet/confirm/{tx_id}` | approver token | Release or reject a held draft or a pending payment |
| POST | `/wallet/pause` | approver or owner token | Stop all agent actions |
| POST | `/wallet/unpause` | owner token | Resume |
| POST | `/wallet/mandate/activate` | owner token | Activate a compiled mandate (out of bounds is HTTP 422) |
| GET | `/wallet/mandate` | none | Active mandate and its hash |
| GET | `/wallet/audit/{invoice_id}` | none | Audit entries for one invoice, plus `verified` |
| GET | `/wallet/audit/ref/{audit_ref}` | none | Audit entries for one action, plus `verified` |
| GET | `/wallet/tx/{tx_id}` | none | The result of one transaction |

Not built: `GET /wallet/registry/{invoice_fingerprint}` and the optional `POST /agent/run`.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `CHAIN_MODE` | `mock` | Only `mock` runs. `fisco` is accepted by the settings but the service still uses the mock ledger. |
| `WALLET_OWNER_TOKEN` | unset | Owner endpoints refuse every request until this is set. |
| `WALLET_APPROVER_TOKEN` | unset | Approver endpoints refuse every request until this is set. |
| `DEMO_MODE` | `0` | `1` allows `skip_offchain_checks`, so the chain alone is tested. |
| `AGENT_CANARY` | unset | Canary string; seeing it in a request is a leak. |
| `INJECTION_MODEL_DIR` | unset | Folder with the pinned classifier model. Unset means rules only. |
| `INJECTION_CLASSIFIER_ACTION` | `log` | `log` audits classifier flags, `hold` holds them for an approver, `block` rejects them. |
| `WALLET_MAX_TX_AMOUNT` | `1500000.00` | Per-transaction cap (THB). |
| `WALLET_DAILY_CAP` | `3000000.00` | Rolling 24h cap (THB). |
| `WALLET_HUMAN_REVIEW_ABOVE` | `837500.00` | Draws at or above this need a human (inclusive). |
| `PLATFORM_FEE_RATE` | `0.003` | Platform fee as a share of face value. |

Money is THB with two decimals.

## Behaviour to know

- **Guard before the ledger.** L0–L4 checks run before any ledger call. Every failure is reported, and the reason is the
  first failing check in layer order. A blocked request never reaches the ledger.
- **Two layers of mandate checks.** The off-chain guard and the on-chain contracts (or the mock mirror) both enforce the
  mandate. Either one stops a payment.
- **Holds.** In `hold` mode, a classifier-only flag stores the draft and returns `pending_approval`. The ledger is not
  called. Release re-runs every hard check. Holds expire after 24 hours.
- **Audit.** Each action writes a hash-chained entry per check and per outcome. Reads return `verified`, which
  is false if any entry has been changed or removed.
- **Decision freshness.** `valid_until` is read through a wallet-side request subclass (`DecisionFreshness`). The
  proper fix is a `contract:` PR that adds the field to shared `PolicyDecision`.

## Known gaps

- No FISCO adapter, and no deployment script yet (`scripts/deploy.py`).
- The classifier is English-only and does not detect jailbreaks. On the held-out v3 set, the rules alone catch 14 of 24
  attacks. The misses are zh, ja, th, and es phrasings and directives with no override verb.
- The orchestrator integration isn't finished (see `docs/orchestrator-integration.md`).
- The 15-minute approval-age rule from CLAUDE.md §5.4 is not implemented.
- The optional agent loop (`POST /agent/run`, CLAUDE.md §7.3) is not built, so the eval skips its two cases.
