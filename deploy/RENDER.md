# Render deployment

The public demo runs on Render from `main`. Owner: PM.

| Render service | Type | URL |
|---|---|---|
| `receivableos-live` | Web service, Docker, free plan, Singapore | https://receivableos-live.onrender.com |
| `receivableos-sme` | Static site | https://receivableos-sme.onrender.com |

## Judge demo (`receivableos-live`)

It builds `deploy/Dockerfile` with the repo root as context. One container runs the four services on 127.0.0.1 and the Streamlit UI on Render's `$PORT`, so only the UI is public. **Docker Command:**

```
/bin/sh -c for s in ocr-ai:8001 policy-ai:8002 agent-wallet:8003 orchestrator:8000; do python -m uvicorn app.main:app --app-dir services/${s%%:*} --host 127.0.0.1 --port ${s##*:} & done; cd ui && UI_MODE=live exec streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT:-3000} --server.headless true
```

Paste it with no quotes after `-c`. Render passes the rest of the line to `sh` as one argument and keeps any quotes in it, so a quoted version fails with `not found`.

Environment, set in the Render dashboard and never in the repo:

- Secrets, each a long random value: `FINGERPRINT_HMAC_KEY`, `BANK_TOKEN_HMAC_KEY`, `ORCHESTRATOR_TOKEN`, `WALLET_AGENT_TOKEN`, `WALLET_RISK_ORACLE_TOKEN`, `WALLET_OWNER_TOKEN`, `WALLET_APPROVER_TOKEN`, `AGENT_CANARY`.
- Fixed values: `CHAIN_MODE=mock`, `SETTLEMENT_TOKEN=tTHB`, `WALLET_CURRENCY=THB`, `WALLET_AMOUNT_DECIMALS=2`, `WALLET_PAYEE_ALLOWLIST=0xSUPPLIER`, `WALLET_SELLER_PAYEE=SELLER:siam-fresh-pack`, `DEMO_MODE=0`, `INJECTION_CLASSIFIER_ACTION=log`, `LLM_PROVIDER=none`.
- Transaction caps in THB: `WALLET_MAX_TX_AMOUNT=1500000.00`, `WALLET_DAILY_CAP=3000000.00`, `WALLET_HUMAN_REVIEW_ABOVE=837500.00`.

The four services and the UI use about 305 MB at rest, which fits the free plan's 512 MB.

The OCR history lives on the container's temporary disk and the mock ledger lives in memory. A restart forgets both, so the happy invoice is a first sighting again. Restart the service before judges try the happy case.

## SME owner mode (`receivableos-sme`)

- Build command: `cd ui/web && npm ci && npm run build`
- Publish directory: `ui/web/dist`
- Environment: `NODE_VERSION=22.22.0`

It runs in sample mode only. Live mode depends on the Vite server's `/api` proxy, which a static host does not have.
