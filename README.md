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
└── data/invoices/       # demo invoices, clean and attack cases
```

Planned, added by their owners when needed: `ui/` (demo screen, port 3000, Policy AI engineer) and `pitch/` (deck, video, business plan).

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

Tests and lint (run tests one service at a time):

```bash
pytest shared
for s in ocr-ai policy-ai agent-wallet orchestrator; do pytest services/$s; done
ruff check . && ruff format --check .
```

Every service answers `GET /health`. Until a service implements its main endpoint it returns a stub response that still matches the contract, so the end-to-end flow runs from day one.

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
