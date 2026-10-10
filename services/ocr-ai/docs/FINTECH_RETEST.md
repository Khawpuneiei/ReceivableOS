# Financial retest and review invariants

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

Use the [wallet/security review packet](HANDOFF.md) to agree authenticated transport, freshness/replay controls, review handling, invoice/decision binding, authoritative PO allocations, registry migration and verified payee ownership. Independent licensed English-first documents and annotations are still needed; generated layout holdout is not independent vendor evidence. Chinese remains experimental, Thai scans remain incomplete and Qwen candidates remain non-authoritative. No production promotion or calibrated fraud probability is claimed.
