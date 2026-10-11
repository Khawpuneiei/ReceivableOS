# Financial retest and review invariants

Historical snapshot: this report records comparison-v2 and its 131-test result. The current local pair comparison is `invoice-po-rules-v3`; see [the current handoff](HANDOFF.md) and [ADR 0006](adr/0006-explicit-line-unit-comparison.md).

10 October 2026, on `ocr/evidence-fraud-graph`. Baseline: `06ad5bc8a757596d9b4ffd9bce597259d3874261`. All document inputs and labels are synthetic. Shared schemas and other-service source remain unchanged. See [the decision](adr/0005-exact-financial-comparison-and-review.md), [regressions](../tests/test_fintech_review.py) and [check provenance](FINTECH_RETEST_CHECKS.json).

## Reproduced discrepancies and fixes

The baseline passed 113 service tests. Thirteen additional cases failed before their respective fixes; the final suite passes **131 tests**, including five additional response-consistency guards. Five existing PyMuPDF/SWIG deprecation warnings remain. Ruff check/format, dependency consistency and whitespace checks pass.

| Trigger | Observed before | Current behavior |
|---|---|---|
| Printed payable differs by USD 0.01, JPY 1 or KWD 0.001 | Matched within a minor-unit tolerance | Exact Decimal mismatch on resolved currency/tax bases |
| Offsetting unit prices leave header totals unchanged | Pair mismatch with handoff review false and compatible confidence 0.97 | Every mismatch requires review, with compatible confidence below 0.80 |
| One SKU below PO, another above PO | All quantity checks became allocation-unknown | Only the under-order SKU becomes unknown; over-order quantity stays mismatch |
| Partial quantity but payable above full PO | Header discrepancy became allocation-unknown | Above-order payable stays mismatch; no remaining-capacity inference |
| Zero invoice face value | No extraction review | Explicit non-positive-amount review, without a fraud accusation |
| Oversized amount, scientific notation or excessive fractional scale | Server exception or unsupported extreme accepted | Bounded unresolved value; required single extraction returns 422 |
| Ambient Decimal precision changes | Local semantic fingerprint changes for the same amount | Context-independent exact canonical identity and 64-digit validation arithmetic |
| Internal arithmetic differs by at most one minor unit | Silent acceptance | Rounding review; larger discrepancies retain arithmetic findings |

Pair response validation rejects downgraded resolved mismatches, unmatched projections with confidence at least 0.80, false handoff review, changed/reordered hashes and inconsistent observation IDs. The optional handoff now declares `comparison_version: invoice-po-rules-v2`. This is internal consistency, not authentication or transaction authorization. Registry-v1 fingerprint bytes and shared required fields retain their recipes; international scope/precision limitations still need an owner-reviewed migration.

## Corpus and integration reruns

The [fresh 80-document Paddle/text evaluation](FINTECH_RETEST_EVALUATION.json) retains the previous measured header results. Counts include expected unresolved annotations; they are not full required-field acceptance rates.

| Language | Header annotation matches | Wrong accepted measured header values |
|---|---:|---:|
| English, primary | 336/336, including 16 correct nulls | 0 |
| Simplified Chinese, experimental review | 112/112 | 0 |
| Thai, secondary | 99/112 | 0 |

[Line-item rerun](FINTECH_RETEST_LINES.json) also retains the previous results: English 88/88 complete tuples (440/440 fields), Chinese 28/28 (140/140), Thai 26/28 (130/140). Thai scan spans replay the fresh header run's diagnostics with rounded confidence; other scans use fresh staged OCR. Header-only commercial PNGs have no annotated lines and confer no line-extraction success. This is generated layout evidence, not independent vendor coverage.

The [smaller demo evaluation](FINTECH_RETEST_DEMO.json) preserves all ten planted duplicate/shared-bank/cluster sequences, independently resolved currency/party/amount mismatches, partial review and unchanged extraction for four injected twins. Its six negative injection documents produce no deterministic alert. These checks do not estimate fraud precision or recall.

[Five actual multipart consumer cases](FINTECH_RETEST_CONSUMERS.json) cover matched, partial, mismatch, international and Chinese responses. The [four-service mock integration](FINTECH_RETEST_INTEGRATION.json) runs the unchanged orchestrator demo: `pending_approval`, then repeat submission blocked by the in-memory registry. Policy/Wallet stubs do not enforce the new handoff; no signature, wallet guard, chain transaction or downstream adoption is tested.

The [Paddle + Qwen API smoke](FINTECH_RETEST_MODEL_SMOKE.json) runs three scanned pairs (six document/model calls). All return review. English and Chinese retain shared projections at confidence 0.79; Thai remains partial with no projection. Qwen still reports injection on benign payment notes in all three pairs, so the unchanged prompt is not promoted as a reliable detector and its candidates cannot repair authoritative fields. Measured pair latencies are diagnostics under a concurrent line-evaluation workload, not deployment benchmarks.

## Licensed synthetic invoice challenge set

The service now includes the [SalorWorks Synthetic Shopify Invoice Test Pack](../../../data/invoices/external/shopify_invoice_test_pack/SOURCE.md), pinned to source revision `bb2e531cfa504e6f7200243620121c523f9f7622` under CC BY 4.0. The pack has 15 fictional invoice scenarios covering multipage documents, regional currencies, discounts, freight/duty, case packs, free quantities, poor scans and a dense bilingual table. This is independently published synthetic evidence, not a real-world vendor holdout or independently audited annotation set.

The first extraction-stack run used the actual local pipeline with English PaddleOCR and Qwen disabled. It evaluated 15 PDFs and 14 single-page PNGs (the multipage PNG contains only page one): **29/232 header fields matched, all 29 matches were currency, and 0/66 expected line rows were extracted**. There were no parser/OCR exceptions. The 10 PDF-text cases and 19 Paddle-backed image cases share the same pattern: common `Invoice`, `Date` and `Bill to` labels are outside the supported alias set, amount labels and values are split across rows, supplier identity is unanchored, and the tables do not match the bounded five-column resolver. The result indicates layout coverage, not that Paddle is the preferred or worse general OCR engine. All these inputs would remain unresolved; the shared compatibility route is designed to reject required-field gaps rather than infer them. Per-input values, timings, model versions and code hashes are in [the external evaluation](EXTERNAL_INVOICE_EVALUATION.json); rerun it with `scripts/evaluate_external_invoices.py` after staging English models.

The latest local run took 221.5 seconds across the 29 serial inputs in this environment, including 19 staged Paddle invocations (Python 3.11.17, PaddleOCR 3.7.0, PaddlePaddle 3.3.0, English PP-OCRv5 mobile recognizer; Qwen disabled). Treat this as a cold/local diagnostic, not a production latency benchmark. A separate TestClient smoke posted the first digital PDF to `/ocr/extract` with an ephemeral key and received the designed 422 required-field response; it did not write observation history. The immediate OCR backlog is deterministic English role/row/table coverage with evidence and hard-negative tests. The pack also contains business concepts absent from the local/shared schema (discounts, freight, duty, tax rate, barcode, unit/pack conversion, free quantities); those need an owner-reviewed contract and downstream policy decision before extraction can make them authoritative.

For a larger research benchmark, [DocILE](https://docile.rossum.ai/) covers key-information localization and line-item recognition across semi-structured business documents, but its dataset requires an access request for research use and has separate data-processing information. It was not downloaded into this workspace; check access terms and the intended evaluation scope before adopting it.

## Reproduce from this service directory

```bash
PYTHONPATH=.:../.. .venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/ruff check . --exclude '*.md'
.venv/bin/ruff format --check . --exclude '*.md'
.venv/bin/python -m pip check
.venv/bin/python scripts/evaluate_reliability.py --paddle --output docs/FINTECH_RETEST_EVALUATION.json
.venv/bin/python scripts/evaluate_lines.py --evidence docs/FINTECH_RETEST_EVALUATION.json --output docs/FINTECH_RETEST_LINES.json
.venv/bin/python scripts/consumer_review.py --output docs/FINTECH_RETEST_CONSUMERS.json
.venv/bin/python scripts/consumer_review.py --models --output docs/FINTECH_RETEST_MODEL_SMOKE.json
.venv/bin/python scripts/eval.py --output docs/FINTECH_RETEST_DEMO.json
.venv/bin/python scripts/smoke_integration.py --output docs/FINTECH_RETEST_INTEGRATION.json
```

Model runs require the previously staged local language profiles and Ollama model. Evaluations use ephemeral keys and temporary observation histories; operational state is not reset. Historical architecture/reliability reports preserve their original source versions. Known test logs and bytecode caches are removed after evidence capture; environments, staged models, private configuration and fixtures remain.

## Remaining owner work

Use the [wallet/security review packet](HANDOFF.md) to agree authenticated transport, freshness/replay controls, review handling, invoice/decision binding, authoritative PO allocations, registry migration and verified payee ownership. Broader independent licensed vendor layouts and human-reviewed annotations are still needed; the new external pack is synthetic and small. Chinese remains experimental, Arabic remains unsupported, Thai scans remain incomplete and Qwen candidates remain non-authoritative. No production promotion or calibrated fraud probability is claimed.
