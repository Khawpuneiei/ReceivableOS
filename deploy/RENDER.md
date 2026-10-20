# Render deployment

The public demo runs on Render from `main`. Owner: PM.

| Render service | Type | URL |
|---|---|---|
| `receivableos-live` | Web service, Docker, free plan, Singapore | https://receivableos-live.onrender.com |
| `receivableos-sme` | Static site | https://receivableos-sme.onrender.com |
| `receivableos-chain` | Web service, Docker, free plan, Singapore | https://receivableos-chain.onrender.com |
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

## Judge demo on a real chain (`receivableos-chain`)

The same stack with the agent wallet on a real FISCO BCOS 3.16.4 chain instead of the mock ledger. It builds
`deploy/Dockerfile.fisco` with the repo root as context and needs no Docker Command: the image runs
`deploy/start-fisco.sh`. On every boot that script:

1. builds an Air chain of `FISCO_NODES` nodes (default 4) on 127.0.0.1 with `build_chain.sh` (node keys and SDK
   certificates are created inside the container, never stored in the image or the repo);
2. generates the five role keys (`deployer`, `agent`, `approver`, `risk_oracle`, `buyer`) with openssl;
3. deploys and wires the five contracts with `services/agent-wallet/scripts/deploy_fisco.py`;
4. starts OCR, policy and the orchestrator on Python 3.11, and the agent wallet with `CHAIN_MODE=fisco` on the
   FISCO SDK's Python 3.10;
5. starts Streamlit on `$PORT`.

Only Streamlit is public; the chain's RPC and P2P ports stay on 127.0.0.1. A restart builds a new, empty chain,
as a restart of the mock demo empties the mock ledger. Any of the eight secrets in the mock demo's list that is
not set gets a fresh random value at boot, because only the processes inside the container use them. Set the
same fixed values and caps as the mock demo, with `LLM_PROVIDER=none` and `FISCO_NODES=1`.

With one node, the chain, the four services and the UI use about 320 MB on Render after a full happy run, which fits
the free plan's 512 MB. Four nodes use about 525 MB, so `FISCO_NODES=4` needs the Standard plan (2 GB), and Render
asks for a card on the account before it allows that plan. On the free plan's CPU a boot takes about two minutes
(25 seconds on a laptop), so the first visit after a sleep waits about three minutes; open it before judges do. The
happy invoice gives real FISCO transaction hashes for TX-1 (register), TX-4 (draw) and TX-5 (settle).

`SMOKE_TEST=1` makes each boot run the happy invoice and the buyer's payment once and log the outcome and the
transaction hashes. That uses up the happy case until the next restart, so leave it unset for judges. The service
was created from the `claude/project-thread-m4tnrm` branch; switch it to `main` under Settings in the dashboard so
it redeploys with the others.

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
