# agent-wallet

Owner: Agent AI engineer. Scope: agent wallet, mandate enforcement, and the whole on-chain layer (Solidity in [`contracts/`](contracts/README.md)), agent-injection guardrails.

Endpoint: `POST /wallet/execute` on port 8003, plus `GET /health`. Request and response models are in [`shared/schemas.py`](../../shared/schemas.py).

Design doc: [`docs/03-agent-wallet.md`](../../docs/03-agent-wallet.md). Assistant instructions for this service: `CLAUDE.md` in this folder (added by the service owner).

Status: stub. The endpoint returns a fixed response that matches the contract so the end-to-end demo runs.

## Endpoints still to build

`POST /wallet/execute` is stubbed. `docs/01-architecture.md` section 5.3 proposes these too, for the five demo transactions; they are the Agent AI engineer's to add (request fields are in that section):

| Endpoint | Purpose |
|---|---|
| `POST /wallet/register` | Register the invoice fingerprint on chain (TX-1) |
| `GET /wallet/registry/{invoice_fingerprint}` | Is this invoice already registered? |
| `POST /wallet/approve` | Record the **credit** approval, signed by the risk-oracle key (TX-2) |
| `POST /wallet/settle` | Settle after the buyer pays (TX-5) |
| `POST /wallet/mandate/activate`, `GET /wallet/mandate` | Set / show the on-chain guard parameters (owner key) |
| `POST /wallet/confirm/{tx_id}` | **Human** approval of a `pending_approval` draw (`X-Approver-Token`, held by the Finance approver, not the mandate owner) |
| `POST /wallet/pause`, `POST /wallet/unpause` | Emergency stop (owner token) |
| `GET /wallet/audit/{invoice_id}`, `GET /wallet/tx/{tx_id}` | Audit trail and tx lookup |

Request models for these are in `shared/schemas.py` (`WalletRegisterRequest`, `WalletApproveRequest`, `WalletSettleRequest`, `MandateActivateRequest`, `WalletConfirmRequest`); every write returns `WalletResult`.

Any new shared field goes through a `contract:` PR first (see the root `CLAUDE.md`).

## Run

From the repo root, with `.env` in place:

```bash
pip install -r services/agent-wallet/requirements.txt
python -m uvicorn app.main:app --app-dir services/agent-wallet --port 8003 --reload
```

## Test

```bash
pytest services/agent-wallet
ruff check services/agent-wallet
```
