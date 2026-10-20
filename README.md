# ReceivableOS

**An autonomous receivables-liquidity agent wallet for SME invoices.**

ReceivableOS takes an SME invoice, verifies it, checks it has not been financed before, scores its credit and fraud risk, decides how much can be advanced against it, and then pays out through an agent wallet whose spending is limited by deterministic, on-chain policy. The AI proposes; the policy guard decides whether the transaction may run.

```
invoice -> OCR + fraud check -> registry duplicate check -> policy + credit risk -> agent wallet -> on-chain tx (FISCO BCOS)
```

Built for [FinTechathon 2026](https://fintechathon.g-ican.com/#/en), Agent Wallet track. Submission deadline: **end of 12 Oct 2026**.

## Team and roles

| Seat | Owns | Where |
|---|---|---|
| PM (P) | Scope, interface spec, integration (orchestrator), PR review, wallet-safety research (spending limits, human approval, audit log, KYC/AML and privacy stance) | `docs/00-scope.md`, `shared/`, `services/orchestrator/` |
| Finance | Use cases, pain-point numbers, business model | `docs/02-finance-domain.md` |
| Agent AI engineer | Agent wallet, mandate enforcement, agent-injection guardrails, the whole on-chain layer | `services/agent-wallet/` (contracts in `services/agent-wallet/contracts/`) |
| Policy AI engineer | Credit policy, credit risk model, mandate schema, demo UI | `services/policy-ai/`, `ui/` |
| OCR AI engineer | Invoice OCR, OCR injection defence, fraud detection | `services/ocr-ai/` |

Shared work: **demo data** (`data/`) is built by the Agent, OCR and Policy engineers, each adding their own cases, and rechecked by the PM. The **pitch pack** (`pitch/`) belongs to PM, Policy AI engineer and Finance.

The scope doc ([docs/00-scope.md](docs/00-scope.md)) is the reference for ownership and interfaces.

## Module map

```
ReceivableOS/
├── README.md            # this file
├── CLAUDE.md            # rules every AI assistant follows in this repo
├── .env.example         # copy to .env, never commit .env
├── docs/                # design docs, one per topic (index: docs/README.md)
├── shared/              # API contract (schemas.py) and money helpers (money.py), PM
├── services/
│   ├── orchestrator/    # POST /flow/run, /flow/repay  port 8000 (PM)
│   ├── ocr-ai/          # POST /ocr/extract            port 8001
│   ├── policy-ai/       # POST /policy/decide          port 8002
│   └── agent-wallet/    # POST /wallet/*               port 8003
│       └── contracts/   # Solidity for FISCO BCOS
├── ui/                  # Streamlit demo and test harness   port 3000
│   └── web/             # SME owner mode (TypeScript)       port 3001
├── pitch/               # deck, video, business plan
└── data/invoices/       # demo invoices, clean and attack cases
```

Two screens sit on the same flow: the Streamlit demo for judges and for testing the OCR, LLM and chain calls, and [SME owner mode](#sme-owner-mode) for the business owner who wants cash for an invoice.

Each service is a small FastAPI app talking JSON over HTTP. Money is a decimal string (`"10000.00"`). The chain is FISCO BCOS, with a mock ledger (`CHAIN_MODE=mock`) so the demo never blocks on the chain.

## How to run

Requires Python 3.11+.

```bash
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# one terminal per service
python -m uvicorn app.main:app --app-dir services/ocr-ai --port 8001 --reload
python -m uvicorn app.main:app --app-dir services/policy-ai --port 8002 --reload
python -m uvicorn app.main:app --app-dir services/agent-wallet --port 8003 --reload
python -m uvicorn app.main:app --app-dir services/orchestrator --port 8000 --reload

# then run the end-to-end flow
python services/orchestrator/run_demo.py
```

Or start all four at once with fresh OCR state (logs in `.stack/`), then stop them:

```bash
scripts/stack.sh start && python services/orchestrator/run_demo.py; scripts/stack.sh stop
```

`scripts/ci_env.sh` writes a `.env` with test-only secrets (mock ledger, no LLM key), the one CI uses.

### One-command deploy (Docker)

```bash
cp .env.example .env     # fill in real secrets, or: scripts/ci_env.sh (test-only values)
docker compose up --build -d --wait
open http://localhost:3000   # UI in live mode; APIs on 127.0.0.1:8000-8003
docker compose exec orchestrator python services/orchestrator/run_demo.py
docker compose up -d --force-recreate ocr-ai agent-wallet   # rehearsal reset: forget seen invoices
docker compose down
```

One image (`deploy/Dockerfile`) runs all five containers on the mock ledger, offline OCR and no LLM key. On
every push to `main`, CD (`.github/workflows/cd.yml`) builds it, runs the demo against the containers and
publishes `ghcr.io/khawpuneiei/receivableos:<sha>` and `:latest`.

Tests and lint (run tests one service at a time):

```bash
pytest shared
for s in ocr-ai policy-ai agent-wallet orchestrator; do pytest services/$s; done
ruff check . && ruff format --check .
```

CI (`.github/workflows/ci.yml`) runs the same on every PR and on `main`: ruff, pytest per service, then the
end-to-end demo on the mock ledger.

Every service answers `GET /health`. Until a service implements its main endpoint it returns a stub response that still matches the contract, so the end-to-end flow runs from day one.

## SME owner mode

SME owner mode is the web app for the business owner. It talks about money and decisions in plain words, with no hashes, gauges or rule codes on the main path. It lives in [`ui/web/`](ui/web/README.md) (TypeScript, React and Vite) and runs on port 3001.

The owner's flow has three steps:

1. **Get cash.** Upload an invoice (PDF, PNG or JPG) or pick one of four sample invoices.
2. **We check it.** The owner watches each check finish. The invoice is read and scanned for hidden instructions and tampering. The ledger confirms it was not financed before. The buyer and the price are checked against the owner's rule, and the wallet checks the rule again before it pays.
3. **Your result.** "You got THB 524,300.00", "We held this invoice" or "We could not finance this invoice", with the reasons in plain words.

There are seven screens behind a sidebar, which becomes a bottom tab bar on a phone:

| Screen | What the owner sees |
|---|---|
| Home | money received, money coming and the cost of financing, plus a banner when something needs them |
| Get cash | the upload or sample invoice, then the checks |
| Invoice result | what they got, the money step by step, lender quotes, how it was checked, ledger receipts |
| Invoices | every invoice and its status |
| Needs you | held invoices, and draws at or above the ask-me limit |
| My rule | the advance, cost, buyer-risk and ask-me limits, as one signed sentence |
| Money & activity | every baht in and out, blocked attempts, the six protection tests, a CSV of receipts |

Run it (Node 22 or newer):

```bash
cd ui/web
npm ci
npm run dev        # sample mode on http://localhost:3001, no backend needed
```

**Sample mode** (`UI_MODE=fixtures`, the default) replays runs recorded from the live stack in `ui/fixtures/`, so it needs no services and no LLM. **Live mode** runs the real flow. Start the four services as above, then:

```bash
UI_MODE=live ORCHESTRATOR_URL=http://localhost:8000 npm run dev
```

The browser only calls `/api/...`. The Vite server forwards those calls to the orchestrator and adds `X-Orchestrator-Token` from `.env` on the server side, so the token never reaches the page.

Not wired yet: "Save and sign" on My rule and "Approve this once" for a large draw need orchestrator routes that don't exist yet (`/flow/mandate/compile` and `/flow/confirm/{tx_id}`). The app says so on screen and changes nothing. The orchestrator pays as soon as an invoice passes the rule, so the result page reports money received instead of asking the owner to accept an offer.

Test it with `npm run typecheck && npm test && npm run build` in `ui/web/`. CI and the Docker image don't include it yet, so run it with npm as shown.

## Docs

| Doc | Topic |
|---|---|
| [docs/00-scope.md](docs/00-scope.md) | MVP scope, ownership, interface spec, demo story |
| [docs/01-architecture.md](docs/01-architecture.md) | Architecture, data flow, trust model |
| [docs/02-finance-domain.md](docs/02-finance-domain.md) | Receivables finance, use cases, pain-point numbers |
| [docs/03-agent-wallet.md](docs/03-agent-wallet.md) | Agent wallet, guard, agent-injection guardrails |
| [docs/04-policy-ai.md](docs/04-policy-ai.md) | Credit policy, credit risk model |
| [docs/05-ocr-ai.md](docs/05-ocr-ai.md) | Invoice OCR, OCR injection, fraud detection |

Each doc lands by its own PR; see [docs/README.md](docs/README.md). Engineers: read [CLAUDE.md](CLAUDE.md) and your service's `CLAUDE.md` before you start prompting.

Background reading lives outside the repo, in the project files: `ReceivableOS-Idea+Architect.md` (design and research) and `receivableos_specialization_roadmap.md` (learning roadmap, Thai).
