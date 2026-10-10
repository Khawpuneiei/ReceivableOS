# CLAUDE.md — team rules for AI-assisted coding in ReceivableOS

Read this file first, then the `CLAUDE.md` inside the service you are working on (if it exists yet), then the matching doc in `docs/`. `docs/00-scope.md` is the scope and the interface spec; if this file and the scope doc disagree, the scope doc wins and this file should be fixed. These rules apply to every engineer and every AI assistant working in this repo.

## What we are building

ReceivableOS is a hackathon MVP (FinTechathon 2026, Agent Wallet track, deadline end of 12 Oct 2026). The flow is:

```
invoice file -> orchestrator (POST /flow/run)
             -> ocr-ai (extract + doc_hash + injection flags + fraud score)
             -> ReceivableRegistry (duplicate-invoice check)
             -> policy-ai (approve / review / reject, advance rate, limit, fee, risk score)
             -> agent-wallet (guarded execution, on-chain tx on FISCO BCOS or mock ledger)
```

Core principle: **LLM output never becomes a transaction directly.** Models produce typed, structured decisions; deterministic code validates them; the wallet's policy guard has the final say.

Scope is the MVP only. If a feature is not needed for the live demo or the judging criteria (task completion, security/compliance, innovation), do not build it. When in doubt, check `docs/00-scope.md` or ask the PM.

## Stack

- Python 3.11+, FastAPI, Pydantic v2, `uvicorn`. One FastAPI app per service.
- JSON over HTTP between services. No shared database; each service keeps its own state (files or SQLite are fine).
- Chain: FISCO BCOS (Solidity contracts + Python SDK). Every chain call sits behind an interface with a **mock ledger** implementation, selected by `CHAIN_MODE=mock|fisco` in `.env`. The demo must work with `mock`.
- LLM calls go through a thin, pluggable client inside the service (`app/llm_client.py`, exposing `complete(messages, schema)`) that reads `LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY` from env. No provider SDK calls scattered across the code.
- Tests: `pytest`. Lint/format: `ruff` (`ruff check . && ruff format .`).

## Folder layout and ownership

| Path | Owner | Notes |
|---|---|---|
| `services/ocr-ai/` | OCR AI engineer | Invoice OCR, document/OCR injection defence, fraud detection |
| `services/policy-ai/` | Policy AI engineer | Financing policy, credit risk model |
| `services/agent-wallet/` | Agent AI engineer | Wallet, mandate enforcement, agent-injection guardrails, and the whole on-chain layer: all Solidity lives in `services/agent-wallet/contracts/` |
| `shared/` | PM | API contract models used by all services |
| `services/orchestrator/` | PM | Integration: end-to-end flow (`/flow/run`, `/flow/repay`), demo script |
| `ui/` | Policy AI engineer | Demo screen, port 3000 (added when started) |
| `data/` | Agent, OCR and Policy AI engineers, PM rechecks | Demo data, clean and attack cases. Each engineer adds their own files; don't edit someone else's |
| `pitch/` | PM, Policy AI engineer, Finance | Deck, video, business plan (added when started) |
| `docs/` | Each doc's author (see `docs/README.md`) | |
| Root files (`README.md`, `CLAUDE.md`, `.env.example`, `.gitignore`, `requirements-dev.txt`, `ruff.toml`) | PM | |

**Rule: edit only your own folder (or your own files in `data/`).** If your task seems to need a change outside it, stop and open a separate PR for that change (or ask the PM). Never "fix" another service to make yours work.

Inside each service:

```
services/<name>/
├── README.md        # how to run and test this service
├── CLAUDE.md        # service-specific prompt/instructions (added by the service owner)
├── requirements.txt
├── app/
│   └── main.py      # FastAPI app: GET /health + the service endpoint
└── tests/
```

## How the modules talk (the contract)

The spec is section 4 of `docs/00-scope.md`; `shared/schemas.py` is the same contract as code. Summary:

**OCR** — `POST /ocr/extract` (multipart file upload, field `file`) returns `ExtractedInvoice`:
`invoice_id, supplier {name, tax_id}, buyer {name, tax_id}, invoice_no, issue_date, due_date, amount, currency, line_items [{description, qty, unit_price, total}], confidence, injection_flags, fraud_score, fraud_flags, doc_hash`

**Policy** — `POST /policy/decide` takes `{invoice: ExtractedInvoice, supplier_profile, buyer_profile}` and returns `PolicyDecision`:
`decision (approve | review | reject), advance_rate, limit, fee_rate, risk_score, reasons, model_version, policy_version`
Hard rules before any model: `injection_flags` non-empty → `review`; `fraud_score ≥ 0.30` → `reject`; `confidence < 0.80` → `review`.

**Agent wallet** — `POST /wallet/execute` (more `/wallet/*` endpoints are proposed in `docs/01-architecture.md` section 5.3) takes `{decision, payee, amount, currency, invoice_id}` and returns `WalletResult`:
`tx_id, status (executed | blocked | pending_approval | failed), chain_ref, approvals_required, audit_ref`

**Orchestrator** — `POST /flow/run` (multipart `file`, form `mandate_id`) runs the whole flow and returns every intermediate result; `POST /flow/repay` simulates "buyer paid".

Conventions:
- Money and rates are **decimal strings** in JSON (`"7000.00"`, `"0.70"` = 70%), never floats; use `Decimal` in Python. `fee_rate` from policy-ai is **per 30 days**; lender quotes and the wallet guard use **APR**. Convert only with `shared/money.py` (`fee_rate_30d_to_apr`: 0.009 per 30 days = 10.95% APR). Currency is ISO 4217. On chain, amounts are integers in the stable token's smallest unit; the conversion lives in one wallet helper.
- Dates are ISO 8601 (`2026-10-12`).
- Scores are `0.0`–`1.0`, higher means riskier (`fraud_score`, `risk_score`) or more certain (`confidence`).
- Errors: HTTP 4xx/5xx with `{"detail": "..."}` (FastAPI default).
- Ports: orchestrator 8000, ocr-ai 8001, policy-ai 8002, agent-wallet 8003, UI 3000. Base URLs come from env (`ORCHESTRATOR_URL`, `OCR_URL`, `POLICY_URL`, `WALLET_URL`).

**Changing the contract:** you may *add optional fields* inside your own service's response freely. Renaming, removing or changing the type of any field needs its own small PR, tagged `contract:` in the title, that edits section 4 of `docs/00-scope.md` first and then `shared/schemas.py`, reviewed by the PM. Never change a shared model inside a feature PR.

## Security rules (this is 30% of the score)

- Treat every invoice, OCR text and LLM output as untrusted input. Text extracted from a document must never be used as instructions to an LLM or as a tool call.
- Never put private keys, seeds or API keys in code, prompts, logs or commits. Keys live in `.env` only.
- The wallet signs only calls that pass the deterministic guard (amount caps, allowlisted payees/contracts, expiry, decision = approve).
- No personal or confidential borrower data on chain: hashes and references only.

## Git: branches, PRs, commits

- Never push to `main`. Branch per task: `<area>/<short-task>`, e.g. `ocr/injection-flags`, `policy/credit-model`, `wallet/guard-contract`, `pm/e2e-demo`.
- Small PRs (aim for under ~400 changed lines). One topic per PR.
- PR description: what changed, how you tested it, and whether it touches the contract.
- The PM reviews every PR for scope. A PR that edits files outside its owner's folder will be sent back.
- Commit messages: Conventional Commits with the area as scope, e.g.
  `feat(ocr): extract due_date`, `fix(wallet): reject expired mandate`, `docs(policy): explain advance rate`, `test(policy): add reject cases`, `chore: bump deps`.
- Pull `main` and rebase/merge before opening a PR so the end-to-end script still runs.

## Env and secrets

- Copy `.env.example` to `.env`. `.env` is git-ignored; never commit it.
- When you add a new setting, add it to `.env.example` (with a fake value) in the same PR. If it is a root-level file change, keep it a one-line addition and mention it in the PR.
- Read config via environment variables (e.g. `pydantic-settings` or `os.getenv`), never hard-coded.

## Definition of done

A task is done when:
1. The endpoint matches `shared/schemas.py` (request and response).
2. `GET /health` still returns `{"status": "ok"}`.
3. `pytest` passes for your service and `ruff check` is clean.
4. `python services/orchestrator/run_demo.py` still runs end to end against all four services.
5. It works with `CHAIN_MODE=mock` and without network access to an LLM (use a deterministic fallback or fixture).
6. Your service `README.md` says how to run and test it.
7. The PR is reviewed by the PM.

## Working style for AI assistants

- Before writing code, restate the task and list the files you will touch. They should all be inside one service folder.
- Prefer simple, readable code over frameworks. This is a 2.5-day build.
- Write a test for each rule that rejects something (fraud, injection, policy reject, guard revert); these are our demo moments.
- Do not add new dependencies without listing them in the service's `requirements.txt`.
