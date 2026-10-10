# orchestrator

Owner: PM. Scope: the end-to-end flow and demo glue (scope doc section 4.4).

Endpoints on port 8000: `GET /health`, `POST /flow/run` (multipart `file`, optional form `mandate_id`), `POST /flow/repay` (form `invoice_id`).

Status: stub. Calls ocr-ai, then an in-memory duplicate check standing in for the `ReceivableRegistry` contract, then policy-ai, then agent-wallet. Lender quotes and settlement are not wired yet. Sending the same file twice shows the duplicate block.

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

## Test

```bash
pytest services/orchestrator
```
