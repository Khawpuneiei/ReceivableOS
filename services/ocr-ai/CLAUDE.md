# OCR AI service guide

This guide does not require Claude Code or a Claude account for offline extraction. The service uses deterministic extraction, optional local PaddleOCR/Qwen-VL, and an optional hosted Anthropic vision candidate adapter authorized by the user on 2026-10-10. Hosted inference requires explicitly configured provider, model and API key; no cloud key is required by the rules path.

## Read these sources in order

1. Read the repository-root `CLAUDE.md` for team ownership, security, shared-contract and review rules.
2. Read `../../docs/00-scope.md` for the project scope and shared API contract.
3. Read `services/ocr-ai/README.md` for setup, endpoints, current operating limits and reproducible commands.
4. Read `services/ocr-ai/docs/ARCHITECTURE.md`, `docs/HANDOFF.md`, and `docs/REVIEW_FOLLOWUP.md` for current architecture, integration boundaries, test evidence and known gaps.
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
- Read ten explicitly labelled English supporting-document templates through `/ocr/cases/verify`, linking claims to an uploaded Invoice/PO. Keep issuer authentication unknown, balances non-authoritative, and cases in review. General bank statements, identity documents, legal contracts and native e-invoice XML are not implemented.

The service does not verify delivery, acceptance, tax registration, legal authenticity, bank-account ownership, PO capacity, prior financing across all lenders, creditworthiness, or permission to release funds. A match, graph, fraud score, confidence, or HTTP 200 is not authorization. Do not describe the fraud score as a probability; it is an uncalibrated aggregation of named rules.

## Current request flow

```text
bounded upload
  -> isolated PDF/image parser and page renderer
  -> use readable PDF text; run staged PaddleOCR only for unreadable pages when enabled
  -> spatial role anchors and explicit five- or six-column line tables
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
| `app/injection.py` | Normalizing multilingual instruction detector (NFKC, zero-width, Cyrillic/Greek look-alikes, leetspeak, letter spacing, base64; English/Thai/Chinese rules) run per span, per joined row and across wrapped lines |
| `app/layout.py`, `app/extract.py` | Spatial rows, explicit role labels, supported line-table shape, evidence-grounded partial extraction and injection patterns |
| `app/normalize.py`, `app/validate.py` | Locale-aware Decimal/date/currency normalization and deterministic validation |
| `app/qwen.py` | Strict local Qwen-VL candidate schema and loopback-only HTTP call |
| `app/llm_client.py`, `app/cache.py` | Hosted vision candidates and bounded process-local TTL caches; no disk persistence of model candidates or raw documents |
| `app/supporting.py` | English supporting-template fields, case relationships and non-authoritative declared balances |
| `app/compare.py` | Evidence-backed invoice/PO checks (`invoice-po-rules-v3`) |
| `app/fingerprint.py`, `app/history.py` | Registry-v1 fingerprint, local scoped HMAC tokens and bounded atomic observation history |
| `app/forensics.py` | PDF edit-trace findings (`pdf-forensics-v1`) from parser marks in `app/worker.py`: covered text, text on a fresh patch in a secondary content stream, one-off font on a money value, incremental revisions that redefine page content |
| `app/promptpay.py` | Thai payment QR (EMVCo PromptPay / bill payment) parser with CRC check; cross-checks QR amount and tax-ID payee against printed, already-grounded fields (`thai-qr-v1`) |
| `app/fraud.py`, `app/graph.py` | Rule findings, uncalibrated noisy-OR score and finding-scoped graph (`graph-rules-v2`, including same-supplier bank-account change candidates) |
| `app/pipeline.py` | Extraction, compatibility projection, comparison, observation, fraud graph and handoff orchestration |

## API and configuration

- `GET /health` returns `{"status":"ok","service":"ocr-ai"}`. It is liveness, not model readiness.
- `POST /ocr/extract` accepts multipart `file`. Unresolved required shared-contract fields return 422 rather than an invented invoice. Optional `Idempotency-Key` binds observation history to the request bytes and route; a reused key with different bytes returns 409.
- `POST /ocr/verify` accepts multipart `invoice_file` and `po_file`. It returns typed partial evidence and `match` / `mismatch` / `unknown` checks. A resolved mismatch cannot be downgraded to a match; unresolved checks require review.
- `GET /ocr/invoices/{invoice_id}` retrieves a POST extraction result using `X-OCR-Result-Token` against `OCR_RESULT_ACCESS_TOKEN`. Results remain in RAM for 15 minutes, at most 500 entries / 8 MiB per process; expiry, eviction or restart yields 404. Missing configuration yields 503, invalid token 401. This token is demo operator access, not tenant authentication.
- `POST /ocr/llm/prewarm` uses the same token and multipart `file`, warms configured candidate caches without writing observations. Cache scope is one process, 128 entries / 4 MiB per reader / 15 minutes. Warm the actual single-worker demo immediately before presenting; restart loses the cache.
- `POST /ocr/cases/verify` accepts a JSON `manifest` form field and repeated `files` uploads, at most 12 files / 20 MiB combined. See `docs/CHECKLIST_AND_DEMO.md` for exact templates and request shape.
- There is no HTTP reset endpoint. In explicit `OCR_DEVELOPMENT_MODE=1`, `/ocr/extract` also accepts only the allowlisted original `data/invoices/demo_invoice.txt` bytes. Its missing jurisdiction/unit evidence requires review; arbitrary text and modified samples still return 415.

Current configured limits are in `app/config.py`: 10 MiB per upload, five PDF pages, 12 million pixels per page/image, 200,000 extracted text characters, parser timeout 20 seconds, Paddle/Qwen timeout 90 seconds, and two concurrent processing slots per server process. A reverse proxy still needs its own whole-request size cap. Multiple server processes multiply the slot limit.

Settings are read from environment variables; see `services/ocr-ai/.env.example` and `app/config.py`:

- `FINGERPRINT_HMAC_KEY` and `BANK_TOKEN_HMAC_KEY` are required outside development mode. Explicit `OCR_DEVELOPMENT_MODE=1` supplies separate public demo keys for missing settings and warns once per setting. Never use these demo keys with real records. `scripts/setup_local.py` generates private random keys for normal setup.
- `OCR_STATE_PATH` defaults to `services/ocr-ai/.state/observations.sqlite`. The history is limited to 500 observations and stops at capacity rather than evicting duplicate evidence.
- `OCR_PADDLE_ENABLED` and `OCR_QWEN_ENABLED` default to `0`.
- `LLM_PROVIDER=anthropic`, `LLM_MODEL` and `LLM_API_KEY` select the optional HTTPS Messages adapter. `OCR_HOSTED_VISION_ENABLED=1` plus a configured key triggers the candidate check; missing model, unsupported provider, invalid output, refusal, timeout, or oversize output causes review. Images, including their printed payment details, are sent to the configured provider; keys/prompts/images never enter service logs or persisted caches. No SDK calls or custom endpoint URLs are accepted.
- Paddle model paths/names are passed to the restricted worker with `OCR_PADDLE_DET_DIR`, `OCR_PADDLE_REC_DIR`, and `OCR_PADDLE_REC_NAME`. Stage models before use; requests must not download model weights. Use matching detector/recognizer assets for English, Thai, or experimental Simplified Chinese. There is no automatic language router.
- `OCR_QWEN_URL` defaults to `http://127.0.0.1:11434`; the accepted model is `qwen3-vl:4b-instruct`. Qwen must remain loopback-only, without tools, credentials, document text in logs, or authoritative field writes. It reads the first page only; a multi-page document must be reviewed for this limitation.
- History reset is an operator-only Python capability requiring development mode and explicit reset permission. Do not add a reset HTTP route.

Use `scripts/setup_local.py` to create ignored local settings safely. It preserves an existing `.env.local`, creates random keys without printing them, and leaves the operational state in this service. Do not replace live or ignored state with an evaluation database.

## Extraction and language limits

The deterministic extractor binds values to explicit labels and source geometry. It supports the aliases in `app/extract.py`, English and Thai labels, a limited experimental Simplified Chinese label set, a five-column `SKU / DESCRIPTION / QTY / UNIT PRICE / LINE TOTAL` layout, and a six-column `SKU / DESCRIPTION / QTY / UNIT / PRICE / TOTAL` layout. Unknown table-shaped headers are explicitly marked unsupported. It does not infer arbitrary table columns, handwriting, Arabic roles, discounts, freight/duty, barcodes, pack conversions, or free quantities. A supplier name inferred from an unlabeled letterhead is retained as ambiguous evidence and requires review. Do not relax these limits by taking the nearest number or name on a page.

`/ocr/verify` compares a line quantity or unit price only when both documents provide a matching unit after Unicode normalization, whitespace compaction and case folding. Missing units make unit, quantity and unit-price checks unknown; differing units mismatch and leave the numeric comparisons unknown. No unit aliases or pack conversions are inferred. The shared single-invoice projection has no unit field; handoff v3 requires `respect_unknown_line_unit_checks`, and a consumer that ignores it cannot safely use local quantity/price comparisons.

English is the primary evaluated language. Thai is secondary and its scan results still have gaps. Simplified Chinese remains experimental and forces review. Arabic and Arabic-English documents are not a supported language profile. Currency code recognition or OCR text visibility does not prove that other invoice fields were extracted correctly.

Numeric grouping and decimal separators require sufficient locale evidence. Monetary calculations use `Decimal`; currency minor-unit precision and explicit source tax basis matter. Do not round away a printed discrepancy. A resolved invoice/PO mismatch requires review. Partial invoicing cannot establish remaining PO capacity without an authoritative allocation ledger.

## OCR engine decision and performance

PDF text/layout is preferred because it is fast, preserves original text evidence, and avoids OCR errors. PaddleOCR is the local scan engine and runs only for unreadable pages when enabled. Use the staged v5 detector plus the language-matched recognizer; recognition scores are not calibrated extraction accuracy.

Qwen3-VL is an optional local experiment, not the primary OCR engine. Both vision readers return nullable candidates under a strict schema and cannot populate missing fields or execute tools. Disagreement, invalid/unavailable output, or an instruction alert routes to review. Qwen reads page one; hosted reads the bounded rendered page set (16 MiB encoded budget). Successful candidates are cached by model/provider/prompt/schema/images, with hosted account identity included without retaining its key. Per-key single-flight deduplicates concurrent identical misses; unrelated network calls proceed independently. Failures are not cached. Qwen can raise benign false alerts; do not promote it as a dependable injection detector. Keep local engines disabled by default; stage model assets explicitly before use.

Instruction detection (`app/injection.py`) recognizes, and never follows, text addressed to an automated reviewer in seven categories: role override, decision coercion, score tampering, payee redirect, tool invocation, exfiltration and obfuscated variants. It adds `OBFUSCATED_INSTRUCTION`, `ENCODED_INSTRUCTION` and `SPLIT_INSTRUCTION` to the existing flags, and the response carries optional `injection_details` (category, technique, channel, evidence refs). Generic `addressed_command` rules catch text that names an AI or automated reviewer and gives it a command; a bare human role ("Sales agent:", "Model: X200", "Reviewer: QA") never counts as an addressee without an AI/automation qualifier. `scripts/injection_eval.py` scores development (190 attacks / 58 benign) and three holdouts. Holdouts v1 and v2 informed the generic rules and are now development data; v3 (50 / 20) was frozen before those rules and is the only unseen number (5/50 before, 27/50 after, 0 false positives). Do not tune rules on v3; write a new holdout before claiming more. Regex rules still miss roughly half of unseen paraphrases, so hidden-channel and model-candidate checks stay in place.

QR decoding uses zxing-cpp in the restricted parser; payloads remain private and never populate invoice fields or trigger link fetches. PDF text extraction uses an infinite clip to inspect off-page content. White text is flagged when rendered background samples are light; ordinary white text on dark headers remains usable. This is a heuristic, not visual tamper or signature verification.

The latest four-scan benchmark uses language-matched Paddle recognizers and records Paddle 24/28 versus Qwen candidates 28/28; English ties at 14/14, while Thai is 10/14 for Paddle and 14/14 for Qwen on two fixtures. Paddle took 9.96–10.99 seconds and Qwen 9.25–11.06 seconds in one run, but Ollama cache state and background load were uncontrolled, so these are not comparable latency targets. Four generated scans do not establish general superiority. Qwen still has false injection alerts in documented HTTP smoke cases and remains candidate-only. New service setup defaults to the English Paddle profile; Thai/Chinese model choice is explicit and there is no per-document language router. These are historical measurements; corpus/evidence documentation is maintained separately on `ocr/corpus-evidence`. Generated JSON reports are ignored and must be reproduced with the scripts.

A scanned-document Paddle worker currently starts per request and initializes its staged model in that process. Do not add a persistent model server without reviewing process isolation, secrets, memory/resource bounds, concurrency, shutdown, and reproducible latency. Benchmark cold and warm paths separately and report exact corpus/model/runtime versions.

## Fraud and data-protection boundaries

Current rule weights are defined in `app/config.py`: exact/semantic duplicate 0.80, near duplicate 0.15, arithmetic mismatch 0.40, PO amount/party/currency mismatch 0.50, shared bank token 0.15, suspicious cluster 0.15. `app/fraud.py` combines unique codes with noisy-OR. These values are not calibrated to real fraud outcomes and must not be mapped to approve/reject thresholds without Policy-owner review.

PDF edit traces (`app/forensics.py`) add `pdf_text_covered` 0.15, `pdf_appended_text_layer` 0.05, `pdf_font_anomaly` 0.05 and `pdf_incremental_update` 0.05; all four together score 0.271, below Policy's 0.30 reject line, so an edit trace alone routes to review via `REVIEW.FRAUD_FLAGS`. Text painted over by a later opaque shape is marked hidden and never fills a field. These are heuristics: stamps and signatures also add content streams, and a forger who regenerates the whole PDF leaves none of these traces. `scripts/tamper_eval.py` reports five forgery styles and four benign edits; `data/invoices/demo/05_tampered.pdf` is the redact-and-retype demo file (amounts raised to THB 856,000 with consistent arithmetic).
Thai payment QR codes (`app/promptpay.py`) are compared, never used as a source: `qr_amount_mismatch` 0.40 and `qr_payee_mismatch` 0.40 (QR pays a different tax ID than the printed supplier, the QR-swap scam) weigh like a PO mismatch; `qr_crc_invalid` 0.15 and `qr_payee_unverified` 0.05 (mobile or e-wallet payee) route to review. Findings never echo the QR payload, payee or amount. Only PromptPay credit transfer (tag 29) and bill payment (tag 30) are parsed; other QR payloads are ignored. `scripts/qr_eval.py` runs eight fictional cases; `data/invoices/demo/06_qr_swap.pdf` is the QR-swap demo file.

Bank accounts are transient private extraction values. Graph links use institution/country/scheme-scoped HMAC tokens; unknown scope or low confidence requires review. Raw bank values and document text must not enter SQLite, graph node IDs, logs, metrics, or public evidence. A shared token is a correlation signal, not proof of common ownership or fraud. Graph export is bounded to the current observation and finding-related evidence.

The legacy shared `invoice_fingerprint` recipe remains unchanged. The local v2 semantic fingerprint and bank token are separate namespaces. Do not alter the shared fingerprint or add fields to `shared.schemas` in an OCR feature change.

## 8.4 `doc_hash` and `invoice_fingerprint`

This section preserves the root guide's Registry contract reference.

- `doc_hash = "sha256:" + sha256(raw_upload_bytes).hexdigest()`; never hash a page render or normalized text instead.
- `invoice_fingerprint = "0x" + HMAC_SHA256(FINGERPRINT_HMAC_KEY, canonical_utf8).hexdigest()`.
- `canonical = "v1|" + supplier_key + "|" + buyer_key + "|" + norm(invoice_no) + "|" + f"{amount:.2f}" + "|" + currency + "|" + issue_date.isoformat()`.
- Party key: tax-ID digits if present; otherwise uppercase name, remove `CO LTD|COMPANY LIMITED|PLC|PCL|LTD|INC` and punctuation.
- Reference normalization: NFKC, uppercase, strip leading zeros from **each numeric run before** removing spaces, `-`, `/`, `_`, `.`. Thus `INV-2026-0042` equals `INV-2026-42` but differs from `INV-202-60042`. This fixes the review's normalization bug; existing local observations need an operator-reviewed reset/migration before adopting changed keys.
- Keep configured keys stable across services and restarts. Development-only fallback matches main's `receivableos-dev-fingerprint-key`, with a warning once. Production mode defaults to fail closed if missing.
- A cosmetic PDF re-save preserves the fingerprint and changes `doc_hash`. The four-file demo now demonstrates this. Exact byte resubmission is separately covered by API tests.
- Shared Registry-v1 has two-decimal/jurisdiction limits; local scoped v2 semantic identity and bank tokens remain separate namespaces. Neither proves authenticity or prior financing elsewhere.

## Evaluation data

- The core PR retains four demo PDFs, the original PM text fixture, and the licensed Thai regression font. Optional corpora are in the companion `ocr/corpus-evidence` PR; generators render regression fixtures into temporary directories. The 80-document reliability corpus is English-primary (48), with experimental Simplified Chinese (16) and Thai (16). These generated layouts are not independent vendor documents.
- The companion branch's `data/invoices/external/shopify_invoice_test_pack/` contains 15 fictional publisher-created invoice scenarios with source `expected.json`, PDF and PNG examples, plus source attribution and checksums. The source declares CC BY 4.0; preserve `LICENSE`, `CITATION.cff`, `SOURCE.md`, and `SHA256SUMS` when sharing the set. The publisher marks supplier identities, registration numbers, addresses, barcodes and amounts as invented. Never present them as genuine supplier records or tax advice.
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

The external evaluation requires staged English Paddle models. The integration smoke in `services/ocr-ai/README.md` uses temporary state and the current local Policy implementation; the latest strict loop verifies injection review and high-fraud rejection. Main now contains the Wallet mock-ledger/guard implementation. This OCR loop does not validate the full Wallet lifecycle, successful drawdown or real chain execution.
