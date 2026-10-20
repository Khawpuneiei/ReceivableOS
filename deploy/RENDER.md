# Render deployment

The public demo runs on Render from `main`. Owner: PM.

| Render service | Type | URL |
|---|---|---|
| `receivableos-live` | Web service, Docker, free plan, Singapore | https://receivableos-live.onrender.com |
| `receivableos-sme` | Static site | https://receivableos-sme.onrender.com |
| `receivableos-credit-risk` | Web service, Docker, free plan, Singapore | https://receivableos-credit-risk.onrender.com |

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

## Credit risk API (`receivableos-credit-risk`)

The same `deploy/Dockerfile`, running policy-ai alone on Render's default port. **Docker Command:**

```
python -m uvicorn app.main:app --app-dir services/policy-ai --host 0.0.0.0 --port 10000
```

No environment variables: it holds no keys, and with `LLM_PROVIDER` unset every route is deterministic. It has no login, so anyone with the URL can call it; it stores nothing. Routes: `POST /policy/decide`, `GET /policy/rules`, `POST /policy/mandate/compile`, `POST /policy/explain`, `GET /health`, and the interactive docs at `/docs`.

```
curl -X POST https://receivableos-credit-risk.onrender.com/policy/decide \
  -H 'content-type: application/json' \
  --data @services/policy-ai/fixtures/requests/01_happy.json
```

## SME owner mode (`receivableos-sme`)

- Build command: `cd ui/web && npm ci && npm run build`
- Publish directory: `ui/web/dist`
- Environment: `NODE_VERSION=22.22.0`

It runs in sample mode only. Live mode depends on the Vite server's `/api` proxy, which a static host does not have.
