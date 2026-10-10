# OCR AI service guide

This file is the working guide for any coding assistant or engineer in `services/ocr-ai/`. It does not require Claude Code, a Claude account, a Claude API key, or any hosted LLM. The running service uses deterministic extraction, optional local PaddleOCR, and an optional local Qwen-VL candidate check.

## Read these sources in order

1. Read the repository-root `CLAUDE.md` for team ownership, security, shared-contract and review rules.
2. Read `../../docs/00-scope.md` for the project scope and shared API contract.
3. Read `services/ocr-ai/README.md` for setup, endpoints, current operating limits and reproducible commands.
4. Read `services/ocr-ai/docs/ARCHITECTURE.md`, `docs/HANDOFF.md`, and `docs/FINTECH_RETEST.md` for current architecture, integration boundaries, test evidence and known gaps.
5. Treat implementation and tests as the source of current runtime behavior. Older reports and prompts are historical unless a newer report confirms them.

If a local note conflicts with the root rules or shared contract, do not silently implement the conflict. Keep `shared/` and other service folders unchanged; raise a contract or owner decision separately.

## Scope and ownership

ReceivableOS is a demo for SME invoice financing. The OCR service owns document reading, invoice-to-uploaded-PO comparison, OCR-local duplicate and graph signals, and a review-oriented handoff. Its output is evidence for downstream owners, not a financing decision.

This service owns `services/ocr-ai/` and its fixtures in `data/invoices/`. The team rules also permit this service's update to `docs/05-ocr-ai.md`. Do not edit shared schemas, the orchestrator, Policy, Agent Wallet, Cybersecurity, or another team's data as part of an OCR change. A shared contract change needs its own `contract:` review with the PM.

For the active OCR/fraud work, the user directed use of `ocr/evidence-fraud-graph`. Check `git status --short --branch` before editing; preserve existing user work and do not switch to `main`. PM review and consumer adoption remain outstanding. Do not merge or message teammates unless explicitly asked.

## Service responsibilities

- Read an uploaded invoice into typed fields with source evidence and explicit missing, ambiguous, conflicting, or unsupported states.
- Compare a separately uploaded invoice and PO using only values grounded in those documents. Unknown evidence stays unknown.
- Detect exact and semantic repeat observations, selected financial inconsistencies, shared scoped bank tokens, and suspicious multi-signal clusters.
- Return an additive graph and unsigned consumer handoff while preserving the existing `shared.schemas.ExtractedInvoice` projection where required fields are resolved.

The service does not verify delivery, acceptance, tax registration, legal authenticity, bank-account ownership, PO capacity, prior financing across all lenders, creditworthiness, or permission to release funds. A match, graph, fraud score, confidence, or HTTP 200 is not authorization. Do not describe the fraud score as a probability; it is an uncalibrated aggregation of named rules.

## Current request flow

```text
bounded upload
  -> isolated PDF/image parser and page renderer
  -> use readable PDF text; run staged PaddleOCR only for unreadable pages when enabled
  -> spatial role anchors and the explicitly supported five-column line table
  -> optional loopback Qwen-VL candidates; disagreement/alert can require review but cannot fill fields
  -> Decimal, date, currency, jurisdiction and arithmetic validation
  -> for /ocr/verify, compare the separately uploaded PO and invoice
  -> bounded SQLite observation, duplicate/graph rules, review findings and unsigned handoff
```

The parser and OCR run in child processes with a restricted environment. The service never follows document links, executes embedded files, or treats invoice text as instructions. Keep that boundary if changing the pipeline.

## Modules

| File | Responsibility |
|---|---|
| `app/main.py` | FastAPI endpoints, request admission and safe HTTP errors |
| `app/ingest.py`, `app/worker.py` | Upload checks, PDF/image parsing, bounded rendering and isolated Paddle worker |
| `app/layout.py`, `app/extract.py` | Spatial rows, explicit role labels, supported line-table shape, evidence-grounded partial extraction and injection patterns |
| `app/normalize.py`, `app/validate.py` | Locale-aware Decimal/date/currency normalization and deterministic validation |
| `app/qwen.py` | Strict local Qwen-VL candidate schema and loopback-only HTTP call |
| `app/compare.py` | Evidence-backed invoice/PO checks (`invoice-po-rules-v2`) |
| `app/fingerprint.py`, `app/history.py` | Registry-v1 fingerprint, local scoped HMAC tokens and bounded atomic observation history |
| `app/fraud.py`, `app/graph.py` | Rule findings, uncalibrated noisy-OR score and finding-scoped graph (`graph-rules-v1`) |
| `app/pipeline.py` | Extraction, compatibility projection, comparison, observation, fraud graph and handoff orchestration |

## API and configuration

- `GET /health` returns `{"status":"ok","service":"ocr-ai"}`. It is liveness, not model readiness.
- `POST /ocr/extract` accepts multipart `file`. Unresolved required shared-contract fields return 422 rather than an invented invoice. Optional `Idempotency-Key` binds observation history to the request bytes and route; a reused key with different bytes returns 409.
- `POST /ocr/verify` accepts multipart `invoice_file` and `po_file`. It returns typed partial evidence and `match` / `mismatch` / `unknown` checks. A resolved mismatch cannot be downgraded to a match; unresolved checks require review.
- There is no mock query mode, invoice-history GET endpoint, or HTTP reset endpoint.

Current configured limits are in `app/config.py`: 10 MiB per upload, five PDF pages, 12 million pixels per page/image, 200,000 extracted text characters, parser timeout 20 seconds, Paddle/Qwen timeout 90 seconds, and two concurrent processing slots per server process. A reverse proxy still needs its own whole-request size cap. Multiple server processes multiply the slot limit.

Settings are read from environment variables; see `services/ocr-ai/.env.example` and `app/config.py`:

- `FINGERPRINT_HMAC_KEY` is required for the compatible extraction and observation flow. `BANK_TOKEN_HMAC_KEY` is required when a scoped bank account is tokenized. Never print or commit either key.
- `OCR_STATE_PATH` defaults to `services/ocr-ai/.state/observations.sqlite`. The history is limited to 500 observations and stops at capacity rather than evicting duplicate evidence.
- `OCR_PADDLE_ENABLED` and `OCR_QWEN_ENABLED` default to `0`.
- Paddle model paths/names are passed to the restricted worker with `OCR_PADDLE_DET_DIR`, `OCR_PADDLE_REC_DIR`, and `OCR_PADDLE_REC_NAME`. Stage models before use; requests must not download model weights. Use matching detector/recognizer assets for English, Thai, or experimental Simplified Chinese. There is no automatic language router.
- `OCR_QWEN_URL` defaults to `http://127.0.0.1:11434`; the accepted model is `qwen3-vl:4b-instruct`. Qwen must remain loopback-only, without tools, credentials, document text in logs, or authoritative field writes. It reads the first page only; a multi-page document must be reviewed for this limitation.
- History reset is an operator-only Python capability requiring development mode and explicit reset permission. Do not add a reset HTTP route.

Use `scripts/setup_local.py` to create ignored local settings safely. It preserves an existing `.env.local`, creates random keys without printing them, and leaves the operational state in this service. Do not replace live or ignored state with an evaluation database.

## Extraction and language limits

The deterministic extractor binds values to explicit labels and source geometry. It supports the aliases in `app/extract.py`, English and Thai labels, a limited experimental Simplified Chinese label set, and the exact five-column `SKU / DESCRIPTION / QTY / UNIT PRICE / LINE TOTAL` layout. It does not infer arbitrary table columns, handwriting, Arabic roles, discounts, freight/duty, barcodes, pack conversions, or free quantities. Do not relax these limits by taking the nearest number or name on a page.

English is the primary evaluated language. Thai is secondary and its scan results still have gaps. Simplified Chinese remains experimental and forces review. Arabic and Arabic-English documents are not a supported language profile. Currency code recognition or OCR text visibility does not prove that other invoice fields were extracted correctly.

Numeric grouping and decimal separators require sufficient locale evidence. Monetary calculations use `Decimal`; currency minor-unit precision and explicit source tax basis matter. Do not round away a printed discrepancy. A resolved invoice/PO mismatch requires review. Partial invoicing cannot establish remaining PO capacity without an authoritative allocation ledger.

## OCR engine decision and performance

PDF text/layout is preferred because it is fast, preserves original text evidence, and avoids OCR errors. PaddleOCR is the local scan engine and runs only for unreadable pages when enabled. Use the staged v5 detector plus the language-matched recognizer; recognition scores are not calibrated extraction accuracy.

Qwen3-VL is an optional local experiment, not the primary OCR engine. It returns nullable candidates under a strict schema, has no tools or API keys, and cannot populate missing fields. Disagreement, invalid/unavailable output, or an instruction alert routes to review. The current prompt raised benign false alerts in the documented smoke cases; do not promote it as a dependable injection detector. When enabled, the current pipeline calls it for each document and limits it to page one, which adds latency and can create unnecessary review. Keep it disabled by default; any future dispatch optimization (for example, only calling it for scanned or unresolved documents) must be measured for missed alerts and preserve the candidate-only boundary.

The small four-scan benchmark recorded Qwen candidate matches of 28/28 versus Paddle's 23/28, with Qwen taking about 12–13 seconds per call and Paddle about 5.6–7.1 seconds. That candidate-only sample is too small to establish general superiority. Later 80-document English/Chinese/Thai tests evaluate the deterministic extraction path, not Qwen-versus-Paddle production quality. See `docs/ENGINE_BENCHMARK.json`, `docs/FINTECH_RETEST.md`, and `docs/RELIABILITY_REVIEW.md` before making engine claims.

A scanned-document Paddle worker currently starts per request and initializes its staged model in that process. Do not add a persistent model server without reviewing process isolation, secrets, memory/resource bounds, concurrency, shutdown, and reproducible latency. Benchmark cold and warm paths separately and report exact corpus/model/runtime versions.

## Fraud and data-protection boundaries

Current rule weights are defined in `app/config.py`: exact/semantic duplicate 0.80, near duplicate 0.15, arithmetic mismatch 0.40, PO amount/party/currency mismatch 0.50, shared bank token 0.15, suspicious cluster 0.15. `app/fraud.py` combines unique codes with noisy-OR. These values are not calibrated to real fraud outcomes and must not be mapped to approve/reject thresholds without Policy-owner review.

Bank accounts are transient private extraction values. Graph links use institution/country/scheme-scoped HMAC tokens; unknown scope or low confidence requires review. Raw bank values and document text must not enter SQLite, graph node IDs, logs, metrics, or public evidence. A shared token is a correlation signal, not proof of common ownership or fraud. Graph export is bounded to the current observation and finding-related evidence.

The legacy shared `invoice_fingerprint` recipe remains unchanged. The local v2 semantic fingerprint and bank token are separate namespaces. Do not alter the shared fingerprint or add fields to `shared.schemas` in an OCR feature change.

## Evaluation data

- `data/invoices/` contains OCR-owned synthetic demo, fraud, Thai/English and generated reliability fixtures. The 80-document reliability corpus is English-primary (48), with experimental Simplified Chinese (16) and Thai (16). These generated layouts are not independent vendor documents.
- `data/invoices/external/shopify_invoice_test_pack/` contains 15 fictional publisher-created invoice scenarios with source `expected.json`, PDF and PNG examples, plus source attribution and checksums. The source declares CC BY 4.0; preserve `LICENSE`, `CITATION.cff`, `SOURCE.md`, and `SHA256SUMS` when sharing the set. The publisher marks supplier identities, registration numbers, addresses, barcodes and amounts as invented. Never present them as genuine supplier records or tax advice.
- `scripts/evaluate_external_invoices.py` evaluates all 15 PDFs and the 14 single-page PNGs against the publisher labels. The multi-page fixture's PNG is page 1 only and is skipped for whole-invoice scoring. It runs the actual local extraction stack with the English Paddle recognizer and Qwen disabled; it does not call the HTTP compatibility endpoint or downstream services. Results are in `docs/EXTERNAL_INVOICE_EVALUATION.json`.
- Treat this small external synthetic pack as a supplemental challenge set, not a production benchmark. If the extractor is changed after inspecting it, classify it as development data and obtain a separate holdout before claiming generalized accuracy. Do not tune thresholds to make this set look successful.

## Safe change workflow

1. Confirm branch/status and read the owning source, tests, scope and current report.
2. State the OCR-owned files being changed. Keep the patch in this service, its own invoice fixtures, and explicitly authorized OCR documentation.
3. Preserve source evidence and abstention. Add a focused regression test for each changed rule, especially conflicting labels, partial tables, private bank values, PO mismatches, idempotency, and graph scope when relevant.
4. Do not add provider SDKs or cloud LLM calls. Any new dependency belongs in the service requirements file and needs a concrete benefit.
5. Run the service checks and the smallest relevant corpus evaluation. Never present synthetic matches as real-world recall, precision, or fraud calibration.
6. Update this guide and the OCR status report when runtime behavior or support claims change. Keep historical reports labeled as historical.

## Reproducible checks

From the repository root:

```bash
services/ocr-ai/.venv/bin/python -m pytest services/ocr-ai -q -p no:cacheprovider
services/ocr-ai/.venv/bin/ruff check services/ocr-ai --exclude '*.md'
services/ocr-ai/.venv/bin/ruff format --check services/ocr-ai --exclude '*.md'
services/ocr-ai/.venv/bin/python -m pip check
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/eval.py
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/evaluate_external_invoices.py
```

The external evaluation requires staged English Paddle models. The integration smoke in `services/ocr-ai/README.md` uses temporary state and existing downstream stubs; it checks transport compatibility only, not Policy/Wallet enforcement or chain execution.
