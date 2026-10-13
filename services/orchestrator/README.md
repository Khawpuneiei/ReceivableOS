# orchestrator

Owner: PM. Scope: the end-to-end flow and demo glue (scope doc section 4.4).

Endpoints on port 8000: `GET /health`, `POST /flow/run` (multipart `file`, optional form `mandate_id`, default
`mdt_001`), `POST /flow/repay` (form `invoice_id`, optional `amount_paid` and `paid_at`),
`GET /flow/audit/{audit_ref}/proof` (the wallet's Merkle inclusion proof for the latest audit entry behind a
wallet result's `audit_ref`; 501 when agent-wallet has no `/wallet/audit/proof` route, 404 for an unknown ref).

Status: wired end to end on the mock ledger. `/flow/run` calls ocr-ai, then the agent wallet's `register` (TX-1:
the on-chain `ReceivableRegistry` is the duplicate check, so a re-saved PDF with the same fingerprint comes back
`blocked: DuplicateReceivable`), then policy-ai. When the decision is `approve` it calls the wallet's `approve`
(TX-2, risk-oracle token, the whole decision plus its `decision_hash`), picks the lender quote from
`data/agent/lender_quotes.json` (highest advance within the approved APR), and calls `execute` (TX-4, agent
token) with the fingerprint, `doc_hash`, `decision_hash`, the seller's payee registry id, the lender and the
mandate. A `review` or `reject` decision stops after policy: the wallet is not called. `/flow/repay` calls the
wallet's `settle` (TX-5) for an invoice this process has run.

The response of `/flow/run` carries every step: `mandate_id, ocr, register, registry, policy, offers, approve,
wallet, outcome`. Steps the flow did not reach are absent.

- `run_demo.py` posts an invoice to `/flow/run`, then `/flow/repay` when the draw executed, and prints every
  step plus a short summary.
- `samples/profiles.json` holds the demo supplier and buyer profiles.
- Demo invoices (clean and attack cases) live in `data/invoices/demo/`, built by the AI engineers and rechecked
  by the PM.

## Run

From the repo root, with the other three services running. Export the `.env` values first; no service loads
`.env` by itself. The orchestrator needs `WALLET_AGENT_TOKEN` and `WALLET_RISK_ORACLE_TOKEN` (the same values the
wallet runs with), ocr-ai needs `FINGERPRINT_HMAC_KEY` and `BANK_TOKEN_HMAC_KEY`, and `WALLET_SELLER_PAYEE`
names the seller in the wallet's payee registry (default `SELLER:siam-fresh-pack`).

```bash
set -a; source .env; set +a
python -m uvicorn app.main:app --app-dir services/orchestrator --port 8000 --reload
python services/orchestrator/run_demo.py                                   # data/invoices/demo/01_happy.pdf
python services/orchestrator/run_demo.py data/invoices/demo/02_injected.pdf  # review: wallet not called
python services/orchestrator/run_demo.py path/to/invoice.pdf --no-repay    # skip the "buyer paid" step
```

Service URLs come from `OCR_URL`, `POLICY_URL`, `WALLET_URL` (ports 8001, 8002, 8003 on localhost by default).
ocr-ai remembers every invoice it has seen, so a second run of the same PDF is a duplicate; reset its demo
history between rehearsals (see `services/ocr-ai/README.md`).

## Test

```bash
pytest services/orchestrator
```

`tests/test_flow.py` runs the flow against fake services (`httpx.MockTransport`) and checks the call order, the
token header on each wallet route and the fields the wallet's guard binds to.
