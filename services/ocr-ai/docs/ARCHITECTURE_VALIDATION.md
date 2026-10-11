# Architecture upgrade validation

Historical architecture increment. The subsequent [financial retest](FINTECH_RETEST.md) records the current source and regression results; the measurements below remain unchanged.

10 October 2026. All document examples and annotations are synthetic. See [architecture](ARCHITECTURE.md) and [consumer handoff](HANDOFF.md). Earlier reports retain their original measurements.

## Header and line evidence

The [80-document Paddle/text evaluation](ARCHITECTURE_EVALUATION.json) measures seven header fields per document. English is primary; Chinese is experimental and always requires review.

| Language | Annotation matches, including expected nulls | Present-annotation matches | Complete five-field line tuples | Wrong non-null measured header values |
|---|---:|---:|---:|---:|
| English | 336/336 | 320/320 | 88/88 | 0 |
| Simplified Chinese | 112/112 | 112/112 | 28/28 | 0 |
| Thai | 99/112 | 99/112 | 26/28 | 0 |

English includes 16 correctly unresolved annotations: absent due dates or ambiguous amounts. Correct nulls do not satisfy required-field extraction. [Line evaluation](ARCHITECTURE_LINES.json) measures 440/440 English, 140/140 Chinese and 130/140 Thai line fields. Header-only PNGs have no annotated lines and confer no line-extraction success. Thai scan line checks replay OCR diagnostics with four-decimal confidence; other scans use fresh staged Paddle.

Generated development/holdout layout families are not independent customer vendors or human-reviewed annotations. Exact anchors and an explicit five-column table schema are validated; arbitrary commercial tables, native Chinese dates/numerals, Traditional Chinese and handwriting remain unverified. No Qwen candidate supplies authoritative fields. These are corpus measurements, not global accuracy or fraud probability estimates.

## Regression and consumer checks

The full service suite has **113 passing tests**, with five PyMuPDF/SWIG deprecation warnings. Its 21 architecture cases cover cross-page/source values, hidden/instruction spans, incomplete-table arithmetic, Chinese/native-form abstention and bank redaction, duplicate/shared-account/cluster graphs, unrelated-history exclusion, unresolved relationships and PO-only injection propagation. Ruff check/format, dependency consistency and whitespace checks pass.

[Demo evaluation](ARCHITECTURE_DEMO_EVALUATION.json) reruns the original smaller fixtures. [Multipart examples](ARCHITECTURE_CONSUMER_EXAMPLES.json) validate local pair and unchanged shared-compatible contracts. [Both-engine HTTP smoke](ARCHITECTURE_MODEL_SMOKE.json) runs six local document extractions as three pairs: English and Chinese have compatible projections but remain reviewable; Thai stays partial. Benign payment-note model alerts persist, so Qwen's prompt is unchanged and its candidates do not repair fields.

[Integration smoke](ARCHITECTURE_INTEGRATION.json) starts four local services with temporary OCR keys/state and runs the unchanged orchestrator demo. The happy result is `pending_approval`; repeat submission is blocked by its in-memory registry. Policy and Wallet are stubs: no guard, signature, chain transaction, new-packet adoption or downstream fraud enforcement is tested. Test processes are stopped and temporary state removed.

## Provenance and remaining work

Reports include input/source-code hashes. Header and line evaluations were repeated after the implementation was frozen, and their run-start hashes match the published source. [Check metadata](ARCHITECTURE_CHECKS.json) records the final source hashes and run distinctions; historical reports are not relabeled. Model smoke exercises isolated one-pair histories; cross-history export isolation is covered by the final regressions.

Test logs and bytecode caches are removed; model assets, the main environment, private ignored configuration, fixtures and evidence reports remain. No operational history is reset. Independent English-first licensed documents and annotations remain necessary. Authentication, signing/freshness, key migration/retention, authoritative PO allocation, payee ownership, policy and wallet adoption await their owners.
