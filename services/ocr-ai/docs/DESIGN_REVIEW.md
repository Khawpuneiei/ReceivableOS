# OCR and Fraud Design Review

Status: Q1–Q3 settled by the user; implementation and synthetic evaluation completed locally on the existing fraud branch. See README and evaluation artifacts for the current behavior.

## Destination

Implement independently grounded invoice and PO extraction, field comparisons, duplicate observations, and explainable bounded graph signals inside OCR ownership. Preserve the existing single-upload shared contract and report measured synthetic-only evaluation with explicit limitations.

## Verified baseline

- Local repository: `<repo>`.
- Branch: `ocr/evidence-fraud-graph`, tracking `origin/ocr/evidence-fraud-graph`, HEAD `b8b2180` at inspection.
- The initial working tree was clean. The branch is two planning commits ahead of `origin/main`; neither commit implements OCR or fraud.
- `app/main.py` reads upload bytes but returns fixed invoice fields and a hard-coded development HMAC fallback.
- Existing contract: `POST /ocr/extract`, multipart `file`, returning `shared.schemas.ExtractedInvoice`. Dates, parties, amount, and invoice number are required; it cannot represent incomplete extraction without fabrication.
- Only an OCR health test exists. Service requirements contain FastAPI, Uvicorn, Pydantic, and python-multipart.
- Orchestrator duplicate state is a process-local set, and policy remains a stub. OCR observations cannot establish durable financing or PO allocation.
- Homebrew Python 3.11.17 is available; system Python 3.9.6 is below the project minimum.
- PyMuPDF 1.28.2 was demonstrated to generate, extract text from, and render an in-memory PDF. Pillow and NumPy are available globally.
- Tesseract and its language packs were not found on PATH or the inspected standard installation paths. OCR wrappers and service/test dependencies are not available globally; no project virtual environment was found in the inspected locations.
- Local fonts cover the tested English and Thai characters. Pillow RAQM shaping is unavailable; glyph coverage does not establish correct Thai layout or OCR accuracy.

## Preparation checks (before implementation)

Created an ignored Python 3.11 environment at `services/ocr-ai/.venv` and installed the existing OCR requirements plus httpx, pytest, and ruff. At that preparation stage no global packages or source requirements were changed. Later implementation added OCR-owned requirements, fixtures and code.

- `services/ocr-ai/.venv/bin/python -m pytest services/ocr-ai -q`: **1 passed**, 1 warning, 0.46 seconds. The warning concerns Starlette's deprecated httpx TestClient path. The sole test checks health; this is not extraction or fraud validation.
- `services/ocr-ai/.venv/bin/ruff check services/ocr-ai`: **All checks passed**.
- `git diff --check`: passed before recording this section.
- Rechecked branch: `ocr/evidence-fraud-graph`. Only OCR-owned glossary/design/ADR documents have been added; implementation code is unchanged.

## Standing rules

- Apply the user's start prompt when it supersedes older starter-pack recommendations: independently read both uploaded files, international normalization, fail safely without secrets, and never expose raw bank-account values.
- Edit only `services/ocr-ai/**`, OCR-owned `data/invoices/**`, and optionally `docs/05-ocr-ai.md`.
- Use English in code, technical documents, and API errors; explain work to the user in Thai.
- No commits, pushes, PR creation, merges, or other remote Git changes are authorized.
- No document-driven commands, model tools, wallet authority, cloud provider, GNN, or cross-service integration.
- Treat the repository's internal freeze as 12 October 2026 at noon Bangkok. Competition scheduling is outside this OCR implementation; do not repeat unverified deadline claims.
- Keep the v1 integration fingerprint recipe for compatibility; do not use its name fallback to merge graph companies. Document any international collision limitations and keep graph resolution separately scoped.
- Preserve raw dates, currencies, Unicode names, and locale evidence. Use Decimal and validated currency minor-unit metadata. Ambiguous dates/numbers, unsupported scripts, and conflicting evidence require review.
- Keep bank evidence private, scoped, and HMAC-tokenized using environment configuration. Missing required secrets fail safely.

## Design tree and decisions

1. **Scope and API boundary — settled**: preserve `/ocr/extract`; add independent OCR-local pair extraction; leave shared schemas and other services unchanged.
2. **Q1 scan engines — settled**: the user explicitly selected PaddleOCR and Qwen-VL together now. Use PDF text first, staged regular Paddle v5 Thai/English recognizer for scans, and local Qwen Instruct as a schema-limited candidate reader. See [local Paddle and Qwen](adr/0002-local-paddle-and-qwen.md).
3. **Q2 incomplete results — settled**: the user authorized the recommended detailed plan. Partial pair fields are typed and nullable with missing/ambiguous/conflicting/unsupported states; compatibility extraction returns 422 when required shared fields cannot be grounded. See [pair boundary](adr/0001-ocr-local-verification-boundary.md) and [contract proposal](CONTRACT_PROPOSAL.md).
4. **Q3 observation history — settled**: the user authorized the recommended detailed plan. Persist bounded OCR-local SQLite observations with scoped tokens and evidence metadata, without raw accounts/source uploads. Partial invoicing has no trusted allocation ledger and remains unknown. See [bounded history](adr/0003-bounded-observation-history.md).
5. **Security and evaluation — settled by start prompt**: format/signature/size/page/pixel/time bounds; models have no tools or action authority; independent language/type evaluation and explicit synthetic-only limitations.

No design frontier remains for the initial OCR-owned slice. The later user-authorized English-primary reliability workstreams and proposed next iteration are tracked in [the reliability map](wayfinder/map.md) and [workstream review](RELIABILITY_REVIEW.md). Production tenancy, trusted financial ledgers and cross-service implementation remain outside OCR ownership.

## Decisions so far

- [OCR-local pair verification boundary](adr/0001-ocr-local-verification-boundary.md).
- [Local PaddleOCR and Qwen-VL experiment](adr/0002-local-paddle-and-qwen.md).
- [Bounded observed history](adr/0003-bounded-observation-history.md).
- [OCR and fraud vocabulary](../GLOSSARY.md): matches, observations and risk signals do not establish delivery, financing, or fraud.

## Proposed implementation slices

1. **Safe document ingestion and real invoice extraction**: `app/main.py`, `app/config.py`, `app/models.py`, `app/ingest.py`, extraction adapter/rules, normalization/validation, fingerprint, service requirements, and focused ingestion/extraction tests. Gate: changed source values change output; shared schema remains valid; unreadable and incomplete files fail safely.
2. **Independent PO extraction and pair checks**: OCR-local verification models, comparator, route, contract proposal, and pair tests. Gate: both documents have independent provenance and match/mismatch/unknown outcomes for reference, parties, currency, basis, and lines.
3. **Duplicate history and explainable graph**: service-local history, typed graph, named versioned findings, and fraud tests. Gate: exact and semantic duplicates differ; benign shared accounts remain review-only; clusters return bounded evidence paths.
4. **Synthetic fixtures, security evaluation, and handoff**: OCR-owned data generator/labels, evaluation script, adversarial tests, README, and OCR results documentation. Gate: reproducible fixture results, supported-language evidence, exact test/lint commands, and honest remaining gaps.

Announce the exact files and acceptance checks before each implementation slice. Run service tests and lint after meaningful changes. Do not describe an HTTP 200 from a placeholder as functional validation.

## Sources inspected

- Root `CLAUDE.md`, `docs/00-scope.md`, `shared/schemas.py`.
- OCR `CLAUDE.md`, `CODEX_START_HERE.md`, `SDLC_OCR_FRAUD_PLAN.md`, and `docs/05-ocr-ai.md`.
- Existing OCR implementation, test setup, service requirements, orchestrator stub and sample profiles.
- User attachment and the Workspace starter pack: architecture/API, SDLC, ADRs, QA/security, repository findings, master prompt, research references, and PO input decision.
- Official [Tesseract installation documentation](https://tesseract-ocr.github.io/tessdoc/Installation.html): supports installation through Homebrew or MacPorts; this is setup guidance, not an English/Thai accuracy result.

## Out of scope

Changes to shared schemas, orchestrator, policy, wallet, UI, remote repository state, real customer documents, live financial actions, legal/compliance conclusions, learned graph models, and unvalidated real-world performance claims.
