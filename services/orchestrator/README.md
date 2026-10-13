# orchestrator

Owner: PM. Scope: the end-to-end flow and demo glue (scope doc section 4.4).

Endpoints on port 8000: `GET /health`, `POST /flow/run` (multipart `file`, optional form `mandate_id`), `POST /flow/repay` (form `invoice_id`, optional `amount_paid`). The two POST endpoints need the header `X-Orchestrator-Token`. Without it, or with no `ORCHESTRATOR_TOKEN` configured, they return 403.

Status: the wallet steps are wired. `POST /flow/run` runs ocr-ai, policy-ai, a mock lender quote, then agent-wallet: register (TX-1), approve (TX-2, only when the policy says `approve`) and execute (TX-4). `POST /flow/repay` settles a financed invoice (TX-5).

- A refusal from ocr-ai, policy-ai or the wallet, or an unreachable service, comes back in the result as `failed: <service> returned HTTP <status>: …`, with HTTP 200. It is not raised as a 500.
- Progress is kept per invoice. A retry resumes from the last step that succeeded and reuses the stored decision, so it does not register again or re-run the policy. The wallet's idempotency keys make the repeated calls safe. A wallet result that was stored as blocked stays blocked under the same key.
- An invoice that is already financed is refused. One waiting for an approver (a draw at or above THB 837,500) is reported as waiting; the orchestrator does not finish it.
- `amount_paid` must be above 0, at most the face value, and at most two decimals. Absent means the full face value. A short payment is allowed, and the wallet's waterfall flags it.
- The in-memory progress does not survive a restart. The wallet's register is the on-chain duplicate check.

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

The orchestrator needs three tokens. `ORCHESTRATOR_TOKEN` is the caller's token: `run_demo.py` sends it as `X-Orchestrator-Token`. `WALLET_AGENT_TOKEN` (register, execute, settle) and `WALLET_RISK_ORACLE_TOKEN` (approve) must match the wallet's environment. Without the wallet tokens the wallet returns 403, and the result says so.

`run_demo.py` uses `data/invoices/demo/01_happy.pdf` by default, because ocr-ai reads PDF, JPEG and PNG only. The `.txt` demo invoice is refused with HTTP 415.

Lender quotes are the mock lenders in `samples/lenders.json` (the same quotes as `data/agent/lender_quotes.json`). The draw is the quoted advance, capped at the policy limit.

## Test

```bash
pytest services/orchestrator
```
