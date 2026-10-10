# ReceivableOS

**An autonomous receivables-liquidity agent wallet for SME invoices.**

ReceivableOS takes an SME invoice, verifies it, scores its credit and fraud risk, decides how much can be advanced against it, and then pays out through an agent wallet whose spending is limited by deterministic, on-chain policy. The AI proposes; the policy guard decides whether the transaction may run.

```
invoice file -> OCR + fraud check -> policy + credit risk -> agent wallet -> on-chain tx (FISCO BCOS)
```

Built for [FinTechathon 2026](https://fintechathon.g-ican.com/#/en), Agent Wallet track. Submission deadline: **end of 12 Oct 2026**.

## Team and roles

| Seat | Owns | Folder |
|---|---|---|
| PM (P) | Scope, shared contracts, end-to-end integration, PR review | `shared/`, `integration/`, `docs/00-scope.md` |
| Finance | Use cases, pain-point numbers, domain knowledge | `docs/02-finance-domain.md` |
| Agent AI engineer | Agent wallet, policy guard on chain, agent-injection guardrails | `services/agent-wallet/` |
| Policy AI engineer | Financing policy, credit risk model | `services/policy-ai/` |
| OCR AI engineer | Invoice OCR, OCR/document injection defence, fraud detection | `services/ocr-ai/` |

## Module map

```
ReceivableOS/
├── README.md            # this file
├── CLAUDE.md            # rules every AI assistant follows in this repo
├── .env.example         # copy to .env, never commit .env
├── docs/                # design docs, one per topic (index: docs/README.md)
├── shared/              # shared API contract (Pydantic models), PM-owned
│   └── schemas.py
├── services/
│   ├── ocr-ai/          # POST /ocr/extract     port 8001
│   ├── policy-ai/       # POST /policy/decide   port 8002
│   └── agent-wallet/    # POST /wallet/execute  port 8003
└── integration/         # end-to-end demo script + sample data, PM-owned
```

Each service is a small FastAPI app. Services talk JSON over HTTP using the models in `shared/schemas.py`. The chain is FISCO BCOS, with a mock ledger fallback so the demo never blocks on the chain.

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

# then run the end-to-end flow
python integration/run_demo.py
```

Tests and lint (run tests one service at a time):

```bash
pytest services/ocr-ai && pytest services/policy-ai && pytest services/agent-wallet
ruff check . && ruff format --check .
```

Every service answers `GET /health`. Until a service implements its main endpoint it returns a stub response that still matches the contract, so the end-to-end script runs from day one.

## Docs

Start with [docs/README.md](docs/README.md). Engineers: read [CLAUDE.md](CLAUDE.md) and your service's `CLAUDE.md` before you start prompting.
