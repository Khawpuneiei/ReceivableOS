# orchestrator

Owner: PM. Scope: the end-to-end flow and demo glue (scope doc section 4.4).

Endpoints on port 8000: `GET /health`, `POST /flow/run` (multipart `file`, optional form `mandate_id`), `POST /flow/repay` (form `invoice_id`).

Status: the wallet steps are wired. `POST /flow/run` runs ocr-ai, a duplicate check, policy-ai, a mock lender quote, then agent-wallet: register (TX-1), approve (TX-2, only when the policy says `approve`) and execute (TX-4). A wallet refusal is returned in the result with the HTTP status or block reason, not raised as a 500. `POST /flow/repay` settles a financed invoice (TX-5). The duplicate check is still an in-memory stand-in for the registry; the wallet's register is the on-chain check.

- `run_demo.py` posts an invoice to `/flow/run` and prints every step.
- `samples/profiles.json` holds the demo supplier and buyer profiles.
- Demo invoices (clean and attack cases) live in `data/invoices/`, built by the AI engineers and rechecked by the PM.

## Run

From the repo root, with the other three services running:

```bash
python -m uvicorn app.main:app --app-dir services/orchestrator --port 8000 --reload
python services/orchestrator/run_demo.py                       # default sample
python services/orchestrator/run_demo.py path/to/invoice.pdf   # your own file
```

Service URLs come from `OCR_URL`, `POLICY_URL`, `WALLET_URL` (ports 8001, 8002, 8003 on localhost by default).

The wallet calls need two tokens, which must match the wallet's environment: `WALLET_AGENT_TOKEN` (register, execute, settle) and `WALLET_RISK_ORACLE_TOKEN` (approve). Without them the wallet returns 403, and the result says so.

`run_demo.py` uses `data/invoices/demo/01_happy.pdf` by default, because ocr-ai reads PDF, JPEG and PNG only. The `.txt` demo invoice is refused with HTTP 415.

Lender quotes are the mock lenders in `samples/lenders.json` (the same quotes as `data/agent/lender_quotes.json`). The draw is the quoted advance, capped at the policy limit.

## Test

```bash
pytest services/orchestrator
```
