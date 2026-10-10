# agent-wallet

Owner: Agent AI engineer. Scope: agent wallet, on-chain policy guard (Solidity in `contracts/`), agent-injection guardrails.

Endpoint: `POST /wallet/execute` on port 8003, plus `GET /health`. Request and response models are in [`shared/schemas.py`](../../shared/schemas.py).

Design doc: [`docs/03-agent-wallet.md`](../../docs/03-agent-wallet.md). Assistant instructions for this service: `CLAUDE.md` in this folder (added by the service owner).

Status: stub. The endpoint returns a fixed response that matches the contract so the end-to-end demo runs.

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
