# OCR-owned invoice and PO verification

This service reads uploaded documents. It has no financing, wallet, delivery, acceptance, or authenticity authority. The implementation replaces the original fixed-response stub on `ocr/evidence-fraud-graph`. The shared schema and other services remain unchanged.

Current architecture uses source geometry for separate panels and explicit line tables, plus experimental Simplified Chinese anchors. Responses add a finding-scoped typed `fraud_graph` and unsigned `handoff` for future wallet/security review. See [architecture](docs/ARCHITECTURE.md), [handoff packet](docs/HANDOFF.md) and [current validation](docs/ARCHITECTURE_VALIDATION.md). Older reports are historical evidence.

## Run from the repository root

Use Python 3.11 or newer. The tested environment is Apple M5, macOS arm64, Python 3.11.17. Core PDF extraction needs no model or cloud credentials.

```bash
python3.11 -m venv services/ocr-ai/.venv
services/ocr-ai/.venv/bin/python -m pip install -r services/ocr-ai/requirements-dev.txt
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/setup_local.py
OCR_PADDLE_ENABLED=0 OCR_QWEN_ENABLED=0 PYTHONPATH=. services/ocr-ai/.venv/bin/python -m uvicorn app.main:app --app-dir services/ocr-ai --env-file services/ocr-ai/.env.local --host 127.0.0.1 --port 8001
```

Setup creates an ignored `.env.local` with separate random HMAC keys, mode 0600, and paths inside this service. It preserves an existing file and never prints keys. Keep keys stable across restarts. SQLite observations are scoped to one deployment/key set; key rotation or multiple tenants require an explicit migration/isolation design. Missing required keys return 503; there is no development-key fallback.

## PaddleOCR and Qwen-VL together

The user selected both engines for this iteration. Stage models explicitly with network access before inference:

```bash
services/ocr-ai/.venv/bin/python -m pip install -r services/ocr-ai/requirements-ocr.txt
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/stage_paddle.py
ollama serve
# In another terminal:
ollama pull qwen3-vl:4b-instruct
PYTHONPATH=. services/ocr-ai/.venv/bin/python -m uvicorn app.main:app --app-dir services/ocr-ai --env-file services/ocr-ai/.env.local --host 127.0.0.1 --port 8001
```

The generated settings enable both engines. Embedded PDF text/layout is preferred; scans use explicitly configured local `PP-OCRv5_mobile_det` and `th_PP-OCRv5_mobile_rec` directories. Request workers do not stage/download models. Qwen uses loopback Ollama, a fixed system prompt, a strict nullable schema, no tools or credentials, and the first page only. It contributes disagreements/alerts, never authoritative replacement values. Additional HTTP smoke documents produced false injection alerts and amount disagreements even after a perfect four-scan candidate benchmark. Null candidates cannot fill missing OCR evidence. Unavailable or invalid Qwen output requires review; missing scan OCR returns 422.

Model selection and measured limitations are recorded in [ENGINE_BENCHMARK.json](docs/ENGINE_BENCHMARK.json) and [the engine decision](docs/adr/0002-local-paddle-and-qwen.md). The default Ollama `4b` tag resolved to Thinking in this experiment; use the explicit Instruct tag. Model tags can change; record and review their digest when updating.

## API

```bash
curl -sS -F file=@data/invoices/demo/01_happy.pdf http://127.0.0.1:8001/ocr/extract
curl -sS -F invoice_file=@data/invoices/demo/01_happy.pdf -F po_file=@data/invoices/demo/purchase_order.pdf http://127.0.0.1:8001/ocr/verify
```

- `GET /health` preserves the original response; it is liveness, not model readiness.
- `POST /ocr/extract`: multipart `file`; response validates as `shared.schemas.ExtractedInvoice`, with OCR-owned evidence, validation/review flags and typed fraud details. Required unresolved fields return 422. Money is Decimal serialized as strings. Review confidence is capped below 0.80.
- `POST /ocr/verify`: separate `invoice_file` and `po_file`; typed partial extraction with nullable field values; checks are `match`, `mismatch`, or `unknown`, with rule codes and independently scoped evidence. The pair status is `matched`, `review`, or `mismatch`. An unreadable upload returns an error. No fabricated PO lookup replaces the uploaded PO.
- Optional `Idempotency-Key` (1–200 characters) binds one history observation to exact request bytes and route. Same-key retries retain the observation and prior duplicate/graph context; different bytes return 409. OCR executes again and document IDs are fresh; this is observation idempotency, not a cached identical HTTP response.

The proposed consumer-facing contract is in [CONTRACT_PROPOSAL.md](docs/CONTRACT_PROPOSAL.md). It is local and unintegrated. Match does not establish delivery, capacity, authenticity, legal validity, or prior financing. Partial invoicing stays unknown without a trusted allocation ledger. Different currencies are never converted or compared as monetary matches.

## Extraction and privacy

Supported rules cover explicit English/Thai and experimental Simplified Chinese anchors, separate panels and `Item: SKU | Description | Quantity | UnitPrice | Total` rows. A five-column whitespace-delimited table with the exact SKU/description/qty/unit-price/line-total header is supported. Arbitrary vendor tables, handwriting, native Chinese financial forms and other scripts are unverified. Unicode names are preserved; observed Chinese remains experimental review. OCR confidence is uncalibrated, not an accuracy probability.

Dates normalize only when ISO or day/month order is supported by explicit source locale or an unambiguous day. Numbers require known locale for grouping/decimal separators; ambiguous values remain unresolved. Currency/country membership uses pinned pycountry 24.6.1 ISO datasets; Babel 2.18 supplies minor units. Unsupported nonmonetary unit codes require review. These snapshots need explicit review/update for new codes. Thai checksum validation applies only to explicitly scoped TH/TAX_ID evidence. Unknown jurisdictions are not assigned Thai rules. Subtotal is treated as the printed pre-tax line base; total must equal subtotal plus tax. There is no tax authority or compliance check.

Raw bank observations stay private and are HMAC-tokenized with known country and scheme. Public evidence contains locations and hashes, not source text or account numbers. A known account repeated in another public field is redacted and unresolved. Source uploads/images, raw bank values, model reasoning and prompts are not persisted by this service. Operators still control Ollama logs, OS access, and backups; this is not a hardened multi-tenant sandbox.

LOCAL accounts also require printed institution evidence. Missing institution forces review without creating an account graph node; v2 tokens distinguish institutions. Older v1 history stays readable but cannot merge with v2. See [the institution-scope decision](docs/adr/0004-institution-scoped-local-bank-tokens.md).

Mixed text/scanned PDFs preserve text spans and OCR only contributes evidence for unreadable pages. When scan OCR is disabled or cannot read a page, the result requires review instead of silently ignoring that page. Rows containing another recognized field label remain ambiguous rather than becoming a party name or reference.

## Observation history and graph

SQLite stores minimal normalized matching fields, scoped entity/bank tokens, document hashes, anomaly codes and evidence locations. It stores observations, never accepted financing or PO balances. Files are mode 0600; history stops at 500 observations instead of silently evicting duplicate evidence. Reset is an operator-only Python method requiring both explicit development mode and reset permission; no reset HTTP endpoint is exposed.

- Exact duplicates compare raw SHA-256 bytes.
- Semantic duplicates use local v2 HMAC over scoped supplier/buyer identifiers, normalized reference, exact Decimal amount, currency and issue date. There is no names-only identity merge.
- The integration `invoice_fingerprint` preserves the legacy v1 recipe: digit-only legal-ID/name fallback, reference normalization, two-decimal amount, currency and issue date. International scope/precision limitations force review and are documented for a separate contract change.
- Bounded NetworkX company, invoice and bank-token nodes use `ISSUED_BY`, `BILLED_TO`, and `PAYABLE_TO` edges. Shared-account paths use only issuer/payment edges. Shared accounts alone score 0.15 and require review. A cluster needs at least two observations, two scoped issuers and two independent anomaly families (amount, identity, currency); it is still a risk signal, not proof of fraud.
- Noisy-OR combines each rule code once. Findings include rule version, reason, tokenized paths and current/historical evidence metadata. A duplicate finding gives a representative prior observation per code.

## Upload limits and boundaries

Allowlist PDF/JPEG/PNG with matching declared MIME and magic signature, maximum 10 MiB per upload, five PDF pages, 12 million pixels per page/image, and 200,000 text characters. Parser and Paddle workers have 20/90 second subprocess deadlines. Two active requests per service process are allowed; excess work returns 429. Configure reverse-proxy request limits as well: multipart parsing/spooling occurs before route-level limits and is not a total request-body cap. Multiple server processes multiply the processing bound.

Encrypted/corrupt files fail safely. Links, attachments, scripts and document instructions are not executed. Parser/OCR children receive an environment allowlist without application/cloud secrets. Injection alerts cover visible instruction patterns, suspicious text styles, Unicode controls, metadata and annotations. QR decoding, comprehensive invisible-overlay detection, OS memory limits, and robust document authenticity/tampering detection are not implemented. Safety does not depend on regex detection or a model following the system prompt.

## Checks and evaluation

```bash
services/ocr-ai/.venv/bin/python -m pytest services/ocr-ai -q
services/ocr-ai/.venv/bin/ruff check services/ocr-ai
services/ocr-ai/.venv/bin/ruff format --check --exclude '*.md' services/ocr-ai
git diff --check
services/ocr-ai/.venv/bin/python services/ocr-ai/datagen/generate.py --font data/invoices/fonts/NotoSansThai-Regular.ttf
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/eval.py
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/benchmark_engines.py
```

Generation is offline with the checked-in SIL OFL Noto Thai font. There are 32 labeled documents: 28 PDFs, four scans, plus five demo aliases. Evaluations use temporary stores and ephemeral secrets; they never reset operational history. [EVALUATION.json](docs/EVALUATION.json) reports extraction by language/type, injection twins, independent pair checks, and planted duplicate/graph sequences. Engine results separately report scanned-document failures and latency. All results are synthetic-only, with no independent real-world holdout and no fraud precision/recall claim.

## English-primary global reliability workstreams

The [80-document corpus specification](docs/RELIABILITY_CORPUS.md) covers English (48), experimental Simplified Chinese (16), and Thai (16), with four synthetic layouts and family-separated development/holdout partitions. The [workstream report](docs/RELIABILITY_REVIEW.md) records all six workstreams, model failures, the disposable grounding prototype, safety regressions and the [consumer review packet](docs/CONSUMER_REVIEW.md).

Stage the language profiles explicitly; then run the reproducible experiments:

```bash
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/stage_paddle.py --language en
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/stage_paddle.py --language zh
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/stage_paddle.py --language th
services/ocr-ai/.venv/bin/python services/ocr-ai/datagen/reliability.py
# Ollama must already be serving qwen3-vl:4b-instruct locally for --models.
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/evaluate_reliability.py --models
# OCR-only rerun after a safety change:
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/evaluate_reliability.py --paddle
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/evaluate_lines.py
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/compare_qwen_prompt.py
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/consumer_review.py
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/consumer_review.py --models
```

For a service language profile set both `OCR_PADDLE_REC_NAME` and `OCR_PADDLE_REC_DIR` to matching staged names/paths. Existing settings preserve the Thai/English recognizer; evaluations use the dedicated English recognizer for the primary track. Exact Simplified Chinese labels are now experimental; Chinese recognition cannot authorize unknown roles or native financial forms. No automatic language routing or production language-coverage claim is made.

Reproduce the current architecture checks from this directory with staged models:

```bash
.venv/bin/python scripts/evaluate_reliability.py --paddle --output docs/ARCHITECTURE_EVALUATION.json
.venv/bin/python scripts/evaluate_lines.py --evidence docs/ARCHITECTURE_EVALUATION.json --output docs/ARCHITECTURE_LINES.json
.venv/bin/python scripts/consumer_review.py --output docs/ARCHITECTURE_CONSUMER_EXAMPLES.json
.venv/bin/python scripts/consumer_review.py --models --output docs/ARCHITECTURE_MODEL_SMOKE.json
.venv/bin/python scripts/eval.py --output docs/ARCHITECTURE_DEMO_EVALUATION.json
.venv/bin/python scripts/smoke_integration.py
```

Integration uses temporary state/free ports, runs the existing mock demo and stops its servers. Policy/Wallet remain stubs; this checks transport compatibility, not downstream fraud controls.
