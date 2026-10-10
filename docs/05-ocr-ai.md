# OCR AI implementation and measured results

Status: OCR-owned English invoice extraction and line-unit comparison improvements are implemented on `ocr/evidence-fraud-graph`, the authorized branch. The full service suite now passes **184 tests**; Ruff check/format, compileall and `git diff --check` pass. The current pair rule is `invoice-po-rules-v3`. Shared schemas and other-service implementations remain unchanged. All document measurements here are synthetic, not production or real-world performance.

The earlier fintech retest is historical: it passed 131 tests for comparison-v2. This increment adds spatial English anchors, explicit five/six-column item-table parsing, conservative financial-row parsing, explicit OCR-local line units, and mandatory review when units are absent or differ. Quantities and unit prices compare only when both documents show the same normalized unit; no conversion or inference occurs. See [the local handoff](../services/ocr-ai/docs/HANDOFF.md) and [unit comparison ADR](../services/ocr-ai/docs/adr/0006-explicit-line-unit-comparison.md).

The independently published challenge pack under `data/invoices/external/shopify_invoice_test_pack/` is synthetic and now serves as development data, not a holdout. The original parser baseline at commit `6885189` matched 29/232 header fields and 0/330 line fields; that evaluator also failed to map the publisher's `supplierSku` key and did not score units, so its line result is not directly comparable. The corrected latest run evaluates 15 PDFs and 14 single-page PNGs: **180/232 header fields (77.59%), 322/396 line fields, and 56/66 expected lines observed**, with no parser/OCR exceptions. No document has all eight header fields: supplier text is visible but remains role-ambiguous because the seller letterhead has no explicit supplier label. Arabic and dense bilingual layouts still have major gaps. The result bypasses HTTP acceptance, history and fraud scoring; publisher labels are not independent annotations. See [the reproducible evaluation](../services/ocr-ai/docs/EXTERNAL_INVOICE_EVALUATION.json) and [source/provenance](../data/invoices/external/shopify_invoice_test_pack/SOURCE.md).

## Implemented behavior

`POST /ocr/extract` preserves multipart `file` and the shared `ExtractedInvoice` shape. It reads actual uploaded values, returns OCR-owned field evidence and typed risk details, and rejects unresolved required fields with 422. It has no fixed demo response or fallback HMAC key.

`POST /ocr/verify` independently reads multipart `invoice_file` and `po_file`. It returns typed nullable partial fields, per-field match/mismatch/unknown checks, independent source evidence, review reasons and risk details. Missing evidence stays unknown. This route is local: [the proposed consumer contract](../services/ocr-ai/docs/CONTRACT_PROPOSAL.md) requires a separate reviewed contract change before adoption by another service.

Embedded PDF text/layout is preferred. Configured local PaddleOCR v5 handles images/scans; new setup uses the English recognizer by default to match the English-primary plan. Thai and Chinese recognizers remain explicit service profiles, with no automatic per-document language router. Qwen3-VL 4B Instruct runs through loopback Ollama as a strict candidate reader with no tools, credentials or transaction authority. It cannot replace deterministic grounded values. Disagreements, invalid output, model alerts and limited page coverage require review.

Decimal arithmetic, explicit source locales, ISO currency/country dataset membership, minor-unit precision, conservative date normalization and scoped legal identifiers are implemented. Unicode names are preserved. Only known TH/TAX_ID evidence receives the Thai checksum. Unlike currencies are not converted. Partial invoicing remains unknown without a trusted allocation ledger. Document matches do not establish delivery, acceptance, authenticity, legal validity, or financing capacity.

## Evaluation data and field extraction

There are 32 labeled documents: 28 PDF text-layer documents and four raster scans, plus five demo aliases. The offline generator uses a checked-in Noto Thai font under its SIL OFL license. Re-generating all 32 labeled files and labels produced identical bytes. English and Thai sets share deliberately simple label layouts and English company names; a separate test verifies preservation of Thai company names. This is not representative international SME data.

[Full core results](../services/ocr-ai/docs/EVALUATION.json): seven fields per document, with expected missing due dates counted as correct explicit nulls. A correct null does not mean the compatibility invoice can be returned.

| Source / language | Document type | Documents | Correct / fields | All seven correct |
|---|---|---:|---:|---:|
| PDF text / English | Invoice | 13 | 91 / 91 | 13 / 13 |
| PDF text / English | PO | 1 | 7 / 7 | 1 / 1 |
| PDF text / Thai | Invoice | 13 | 91 / 91 | 13 / 13 |
| PDF text / Thai | PO | 1 | 7 / 7 | 1 / 1 |

These totals include clean, changed, incomplete, duplicated, injected, mismatched, partial and graph-sequence documents. The fields are document number, total, currency, issue date, due date, supplier name and buyer name. Independently extracted PO checks include reference, scoped identities/countries/schemes, names, currency, tax basis, amounts and aligned SKU descriptions/quantities/unit prices.

## PaddleOCR and Qwen-VL experiment

The user explicitly chose both engines now. Tested environment: Apple M5, 16 GB RAM, macOS arm64, Python 3.11.17, PaddlePaddle 3.3.0, PaddleOCR 3.7.0 and Ollama 0.34.4. Paddle uses CPU with `PP-OCRv5_mobile_det` and selects `en_PP-OCRv5_mobile_rec` or `th_PP-OCRv5_mobile_rec` to match the tested fixture language. Qwen uses local `qwen3-vl:4b-instruct`, digest prefix `ee4b975b58c1`.

The latest four-scan rerun uses exact scalar matches, including money formatting. The full records and limitations are in [ENGINE_BENCHMARK.json](../services/ocr-ai/docs/ENGINE_BENCHMARK.json):

| Generated scan | Paddle correct / 7 | Qwen candidates correct / 7 | Paddle seconds | Qwen seconds |
|---|---:|---:|---:|---:|
| English invoice | 7 / 7 | 7 / 7 | 9.961 | 10.721 |
| English PO | 7 / 7 | 7 / 7 | 10.898 | 10.245 |
| Thai invoice | 5 / 7 | 7 / 7 | 10.574 | 11.056 |
| Thai PO | 5 / 7 | 7 / 7 | 10.985 | 9.245 |

The benchmark now selects the English or Thai Paddle recognizer to match each fixture. Paddle matches 24/28 scalar fields and Qwen candidates match 28/28; English ties at 14/14, while the two Thai fixtures favor Qwen. This is one four-scan run with uncontrolled cache state/background load, so timings are not a stable comparison. Four generated scans cannot establish general accuracy, and Qwen's candidates still do not establish source grounding or authoritative extraction. [Additional actual HTTP smoke cases](../services/ocr-ai/docs/HTTP_SMOKE.json) changed invoice references and produced false model injection alerts and an amount disagreement on normal documents. Deterministic PDF values and comparison checks remained correct; the pair result safely required review. Thai scan pair verification returned 200 with typed partial evidence, null compatible invoice, and review/unknown checks. Single Thai scan extraction returned 422 because Paddle missed required issue-date/buyer evidence. English scan extraction with both engines returned 200 and a shared-valid invoice.

Earlier Thinking-tag, permissive-schema and subtotal-confusion experiments are consolidated in [engine selection notes](../services/ocr-ai/docs/ENGINE_SELECTION_NOTES.md). Use the explicit Instruct tag and require all nullable schema fields. Warm caches and background load were uncontrolled. The followup adds English-primary multilayout and experimental Chinese synthetic testing; there is still no independently sourced real-world benchmark or handwriting validation.

The Paddle engine and recognizer choice follow [official OCR documentation](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html); Mac CPU installation follows [Paddle documentation](https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/macos-pip_en.html). Qwen's explicit tags and structured output interface follow [Ollama tags](https://ollama.com/library/qwen3-vl/tags) and [structured outputs](https://docs.ollama.com/capabilities/structured-outputs). Published language coverage is not measured accuracy here.

## Injection and risk signals

Core deterministic injection evaluation: four alerts out of four injected twins, all seven values unchanged on all four; zero alerts among six clean/benign-note negatives. This excludes Qwen alert quality. False Qwen alerts in HTTP smoke tests demonstrate why those figures must not be presented as end-to-end model false-positive rates. Alerts cover instruction patterns, suspicious styles including non-rendering PDF text, Unicode controls, metadata and annotations. No document content can execute commands or trigger financial actions.

Ten planted English/Thai risk sequences triggered every expected code and had evidence paths. They evaluate named rule conditions, not real-world fraud precision/recall.

| Sequence (each tested in English and Thai) | Codes / behavior | Score without graph | With graph |
|---|---|---:|---:|
| Same bytes resubmitted | Exact and semantic duplicates remain separately explained | 0.96 | 0.96 |
| Same invoice re-rendered | Semantic duplicate, different byte hash | 0.80 | 0.80 |
| Same scoped reference, changed amount | Arithmetic inconsistency plus candidate near duplicate | 0.40 | 0.49 |
| Benign shared account | Distinct scoped issuers sharing a token require contextual review | 0 | 0.15 |
| Independent anomalous cluster | PO currency/identity discrepancies plus shared-account cluster | 0.75 | 0.819 |

The bounded NetworkX graph has invoice, company and bank-token nodes, and `ISSUED_BY`, `BILLED_TO`, `PAYABLE_TO` edges. Company resolution requires scoped legal identifiers; names alone cannot merge entities. Shared-account paths explicitly traverse issuer/payment edges. Clusters require at least two anomalous observations, two distinct scoped issuers and two independent anomaly families. Correlated arithmetic/PO amount codes count as one amount family. Shared accounts/clusters remain contextual signals, not proof of collusion or fraud. Noisy-OR scores combine unique codes and are not calibrated probabilities.

SQLite holds up to 500 observations, with minimal normalized values, hashes, scoped HMAC tokens, anomaly codes and evidence locations. It has byte/fingerprint indexes, transactionally bound retry keys, mode-0600 files and development-only reset controls. It stores observations, not accepted financing or PO allocations. Public findings resolve current/historical evidence locations without exposing raw account values. Legacy v1 integration fingerprints remain unchanged; local semantic v2 separately includes jurisdiction and identifier scheme. International v1 collisions/precision limitations require review and an explicit future migration.

## Safety and limitations

Upload allowlist and MIME/signature checks cover PDF/JPEG/PNG, with 10 MiB per file, five PDF pages, 12 million pixels per page/image, 200,000 text characters, 20-second parser and 90-second Paddle subprocess deadlines, bounded local model responses and two processing slots per server process. Corrupt/encrypted files and unavailable required engines/secrets fail safely. Filenames do not select outputs or file paths. Parser/OCR child environments omit application/cloud secrets.

Currency/country membership uses pinned pycountry 24.6.1 ISO datasets; tested Babel 2.18 supplies minor units. New/unsupported codes and nonmonetary units require review, and metadata updates need explicit validation. This is not a live standards/regulatory service.

LOCAL bank tokens now require printed institution evidence and use a distinct v2 namespace; missing institution forces review without a graph token. Mixed digital/scanned documents cannot silently ignore unreadable pages. Ambiguous merged columns and all observed conflicting account values are guarded/redacted. See [the bank-scope decision](../services/ocr-ai/docs/adr/0004-institution-scoped-local-bank-tokens.md).

Remaining work: independently sourced vendor layouts and general tables; native Chinese financial forms; Thai recognition recovery; model false-alert/amount quality; authoritative banking identity and migration; tenant isolation, key rotation and retention; authenticated access; trusted financial ledgers; request/resource limits and broader visual tamper handling. The OCR-owned integration loop now asserts actual Policy hard guards and records two violations: the current stub approves injected and inflated invoices. QR payload decoding is implemented in the restricted parser; real on-chain controls remain untested.

## Checks and handoff

Initial implementation validation (superseded test counts are retained as historical context):

- `services/ocr-ai/.venv/bin/python -m pytest services/ocr-ai -q`: 66 passed, 5 PyMuPDF/SWIG deprecation warnings.
- `services/ocr-ai/.cache/core-check/bin/python -m pytest services/ocr-ai -q`: 66 passed in a fresh environment with only core/dev requirements, without PaddleOCR or Ollama; 6 dependency deprecation warnings, including Starlette's httpx TestClient warning.
- `services/ocr-ai/.venv/bin/ruff check services/ocr-ai`: passed.
- `services/ocr-ai/.venv/bin/ruff format --check --exclude '*.md' services/ocr-ai`: passed.
- `services/ocr-ai/.venv/bin/python -m pip check`: no broken requirements.
- `git diff --check`: passed.
- `services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/eval.py`: 196/196 core field matches, 4/4 injected twins unchanged, 10/10 expected risk sequences.
- `services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/benchmark_engines.py`: four generated scans with language-matched Paddle recognizers, Paddle 24/28 and Qwen candidates 28/28; detailed models, fields and timings retained. Cache state is uncontrolled.
- Offline generator rerun with the checked-in Thai font: all 32 labeled files plus labels byte-identical.
- Actual local Uvicorn and HTTP uploads validated the shared response and independent pair evidence. Servers started for testing were stopped; synthetic observations were preserved in ignored test state, leaving the default operational state path fresh.

Setup, commands, private-key creation and staged model paths are in the [service README](../services/ocr-ai/README.md). New code is grouped into ingestion/workers, OCR-local models/extraction/normalization, pair comparison, scoped fingerprint/history/graph, synthetic generation/evaluation and tests. Resolved terms and decisions are in the [glossary](../services/ocr-ai/GLOSSARY.md), [design review](../services/ocr-ai/docs/DESIGN_REVIEW.md), and OCR-owned ADRs.

## English-primary reliability followup

The user authorized six reliability workstreams: [the 80-document corpus](../services/ocr-ai/docs/RELIABILITY_CORPUS.md) has 48 English, 16 experimental Simplified Chinese and 16 Thai documents. Four generated layouts have family-separated development/holdout partitions. [The workstream review](../services/ocr-ai/docs/RELIABILITY_REVIEW.md) distinguishes the 36-call Qwen baseline, prompt experiment, post-safety OCR rerun, disposable grounding prototype, regression checks and cleanup.

The earlier [consumer packet](../services/ocr-ai/docs/CONSUMER_REVIEW.md) includes multipart examples and review/unknown handling. Shared-contract adoption and international fingerprint migration still require their owner.

## Earlier architecture increment (historical verification)

[Architecture](../services/ocr-ai/docs/ARCHITECTURE.md) separates spatial roles, deterministic validation/comparison, bounded history and typed graph export. English/Chinese/Thai header annotation matches are 336/336, 112/112 and 99/112; English includes 16 correct unresolved values. Complete line tuples are 88/88, 28/28 and 26/28. These counts cover the generated corpus only; Chinese always requires experimental review.

Responses add versioned, finding-scoped graphs and an unsigned [wallet/security handoff](../services/ocr-ai/docs/HANDOFF.md) with source hashes, versions and review/risk signals. PO-only injection propagates to the compatible invoice projection. That increment passed 113 tests at the time; the current suite passes 184 tests. The unchanged mock demo returns pending approval and blocks repeat registration. No chain execution or consumer adoption is implied. Branch updates are authorized; PM review and cross-service integration remain separate.

## Checklist audit, hosted adapter and financing evidence case (11 October 2026)

The user authorized an optional hosted LLM adapter in addition to local Qwen. `app/llm_client.py` centralizes Anthropic Messages calls using `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`; no cloud key means deterministic rules remain operational. Strict typed candidates cannot fill or replace grounded fields. Tests mock keyed transport, cache hit/no call, account isolation, refusals, invalid schemas, tools, oversized responses, and disagreement review. Live hosted-model accuracy is not measured.

Private parser extras now include rendered pages, PDF metadata/annotations and bounded QR payloads. Off-page text is inspected without clipping. QR content never supplies invoice fields or triggers URL fetching. White-on-dark headers are treated as visible using rendered background samples. These heuristics do not verify signatures or altered pixels.

[Checklist evaluator](../services/ocr-ai/docs/CHECKLIST_EVALUATION.json) prints the following table from `scripts/eval.py`. It measures rules-only synthetic documents, not the optional model's false-alert rate.

| Metric | Result | Dataset / target |
| --- | --- | --- |
| Clean PDF exact field accuracy | 28/28 = 100% | 4 English/Thai PDFs, 7 scalar fields; >=90%, aim98% |
| Injection catch | 16/16 = 100% | 8 attack mechanisms, 2 source twins each; >=95% |
| Attack success, changed grounded scalar fields | 0/16 = 0% | Same 7 fields; 0% target |
| Hard-negative false positives | 0/20 = 0% | Payment notes, benign QR and white-on-dark headers; <=5% |
| Planted fraud precision / recall | 100% / 100% | TP8 / FP0 / FN0 / TN4 at score>=0.30; 12 sequences |
| Supporting-case automation | 6/6 | Correct linkage, receipt shortage, unrelated credit, dispute, excess credit, missing confirmation |

The independent vendor-layout development pack above remains at 77.59% header accuracy; these small template results do not establish the global >=90% target. Simplified Chinese remains experimental/review; native Chinese financial forms and Thai scan gaps remain unresolved.

`GET /ocr/invoices/{id}` returns the extraction plus extras through a private operator token, using a bounded RAM result cache. `POST /ocr/llm/prewarm` warms model caches without inserting invoice observations. Both caches have a 15-minute TTL, require a single-worker demo for predictable hits, and disappear on restart. Actual local Qwen verification made 8 requests with 5 hits including every round-two request; its isolated verification server was then stopped. Prewarm the running demo again before presenting. Actual English Paddle PNG/JPEG smoke tests each returned 200, all seven evaluated fields matched, with no review. See [real model evidence](../services/ocr-ai/docs/CHECKLIST_MODEL_CHECK.json).

A [12-document fictional case pack](../data/invoices/financing_case/manifest.json) adds ten labelled supporting templates to Invoice/PO: delivery note, goods receipt, buyer confirmation, credit note, remittance advice, assignment notice, company registration, masked bank confirmation, beneficial-owner declaration reference and insurance certificate. `/ocr/cases/verify` checks source-grounded references, scoped invoice party IDs, quantities/units, buyer acceptance claims, duplicate supporting references and declared adjustments. Unrelated/invalid/duplicate adjustments do not reduce the displayed balance; it is never an authoritative ledger. Issuer authenticity remains unknown and all supporting cases require review. No registry, bank, signature, legal, ownership or settlement verification is implied.

Generation through `datagen/generate.py --seed` now creates polished demos and the case pack; ReportLab invariant metadata makes matching-seed output byte-identical. Regression label PDFs remain temporary rather than reintroduced as old checked-in samples. [Fresh-clone verification](../services/ocr-ai/docs/RELEASE_CHECK.json) installs only core/dev requirements, generates data, starts on port8001, runs pytest/Ruff and checks POST/GET without a cloud key or local-model dependency. See [full checklist and usage](../services/ocr-ai/docs/CHECKLIST_AND_DEMO.md).

The checked-in ordered demo is now replayed in one temporary state: happy invoice → injected invoice → inflated invoice → exact duplicate. It passes approve-candidate / review / reject / reject expectations: cases 02 and 03 use distinct invoice numbers, the injected invoice has no duplicate flag, the inflated invoice triggers `math_inconsistent` at 0.40, and the final exact duplicate triggers both `duplicate_invoice_hash` and `duplicate_fingerprint` at 0.96. `scripts/demo_order.py` is included in the release gate; its result is an OCR evidence gate and does not call Policy. The actual Policy integration remains separate and records its two hard-guard violations. Current verification passes 184 tests both locally and in the fresh clone; OCR checks pass while overall `release_ready` remains false until the Policy owner fixes those controls.

The 11 October owner packet [POLICY_INTEGRATION_HANDOFF.md](../services/ocr-ai/docs/POLICY_INTEGRATION_HANDOFF.md) spells out expected guard precedence, the lower-case OCR versus uppercase Policy flag naming mismatch, a direct Policy test matrix, and a versioned evidence-bundle proposal. The independent-source research in [DATASET_ACCESS_AND_HOLDOUT.md](../services/ocr-ai/docs/DATASET_ACCESS_AND_HOLDOUT.md) finds DocILE access-token gating, XFUND's non-commercial form-only limits, and SROIE's receipt-only scope/data-terms gap. No external data was downloaded; a permissioned holdout and real fraud labels remain open dependencies.

Release remains pending: Policy still fails two hard guards, live hosted inference needs provider configuration, global held-out accuracy is unproven, and PM review/PR merge is not completed. The supplied phrase “Sun 12 Oct” conflicts with the 2026 project calendar: 12 October 2026 is Monday.
