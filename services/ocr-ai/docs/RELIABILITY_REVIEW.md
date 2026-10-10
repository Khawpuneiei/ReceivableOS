# English-primary OCR and fraud reliability review

Historical report before spatial-rules-v2. See [current architecture validation](ARCHITECTURE_VALIDATION.md) for later role, table and graph improvements. The measurements below describe their original snapshots.

Date: 10 October 2026. Branch: `ocr/evidence-fraud-graph`. All six authorized workstreams were exercised locally; consumer adoption is still an owner decision. No commits, remote changes, shared-schema edits or other-service implementation occurred.

## Outcomes by workstream

| Workstream | Work performed | Decision / remaining gap |
|---|---|---|
| Evaluation corpus | Generated 80 English-primary, family-separated multilayout documents; verified byte-identical regeneration and input hashes | Useful synthetic stress evidence; independent source/annotation validation remains outstanding |
| Extraction diagnosis | Compared PDF/Paddle results by language/layout, inspected actual Thai spans and bbox offsets, staged dedicated English and Chinese recognizers | Prioritize English columns/tables; Chinese recognition alone does not supply field roles; Thai tone marks and row geometry still cause missing fields |
| Qwen reliability | 36 baseline calls on 24 scans, with repeats; 12 prompt-variant calls on benign and explicit AI-instruction cases | Keep the tested live prompt and candidate-only role; the variant still has excessive benign alerts and is not promoted |
| Grounded recovery | Disposable prototype checked saved candidates against source anchors, unique values, confidence and source locations; tests reject wrong subtotal, hidden values, conflicting totals and instruction text | Recovered 14 previously unresolved header fields across four Thai scan documents with no observed wrong grounded value; not enough evidence to promote into the live pipeline |
| Regression/state/graph checks | Added concurrency/restart, bank institution, mixed-page, monetary, privacy, model failure and incomplete-table checks; fixed concrete safety failures | 92 tests pass with models installed and in a core-only environment; resource/tenant/QR/authenticity limitations remain explicit |
| Consumer contract | Prepared actual schema-validated multipart examples, a both-engine scan API smoke and fingerprint/review packet | Ready for owner review; shared adoption and registry migration have not been agreed or implemented |

## Header and line evidence

The [post-safety OCR evaluation](RELIABILITY_EVALUATION.json) measures seven header fields on all 80 documents. The [baseline](RELIABILITY_BASELINE.json) retains the earlier model experiment and pre-guard values; the [line evaluation](LINE_EVALUATION.json) measures SKU, description, quantity, unit price and total separately.

| Language | Documents | Correct header fields | All seven annotation matches | Correct complete line tuples / expected |
|---|---:|---:|---:|---:|
| English | 48 | 263 / 336 | 32 / 48 | 68 / 88 |
| Simplified Chinese | 16 | 0 / 112 | 0 / 16 | 0 / 28 |
| Thai | 16 | 73 / 112 | 6 / 16 | 22 / 28 |

There were 29 English and 9 Thai wrong non-null header values in the pre-guard run. Recognized neighboring labels are now treated as ambiguous, reducing that observed count to zero on this generated set. Missing/ambiguous fields remain missing; the field-match totals did not increase. This is abstention evidence, not proof that all documents can be extracted.

Correct nulls count as annotation matches, so an all-seven match can include an intentionally missing due date and does not establish compatibility or acceptance. Header-only PNGs have no annotated lines and do not contribute successful line tuples. Commercial table PDFs expose the unsupported general-table layout. Neither corpus labels nor truth regions were independently human-reviewed.

The dedicated English recognizer reads the evaluated stacked scans well; multi-panel field grouping remains unreliable. Thai scan diagnostics show both recognition errors (`วันที่ออก` loses its tone mark) and geometry errors: label/value top coordinates can differ by exactly five pixels, failing the existing strict row threshold. The prototype uses vertical overlap and explicit anchors; it does not fuzzy-correct missing Thai marks or invent reference numbers.

Chinese native labels are absent from the live label map, and observed Chinese script still requires review. Qwen's ability to read the example values does not resolve this missing deterministic layer. Traditional Chinese, native date notation, handwriting, currency symbols and arbitrary vendor documents were not validated.

## Model reliability and grounding

The baseline Qwen reader matched 252/252 evaluated header candidates across 36 calls, representing 24 unique scans. It incorrectly reported injection on every call: all sampled scans contain a benign payment note. That deliberately narrow negative set is not a general false-positive estimate. Repeats are not independent documents.

The [prompt experiment](QWEN_PROMPT_EXPERIMENT.json) explicitly distinguishes ordinary payment notices from AI-directed instructions. It returned valid structured outputs in 12/12 calls, correct amounts in 12/12, and detected all 6 printed AI instructions, but still falsely flagged 5/6 benign cases. The live prompt remains unchanged. Benign scans and attacked PDFs differ in rendering; these counts are not calibrated recall/FPR or a universal security guarantee.

The [grounding followup](GROUNDING_EXPERIMENT.json) replays saved model candidates against current-run Thai OCR evidence with matching input hashes. Four documents yield 14 additional source-anchored fields, including issue date/amount in split layouts and names/due date/amount/currency in panels. Conflicting/hidden/unanchored values and wrong monetary roles abstain. Evidence scores were rounded to four decimals in diagnostics. The prototype has no API field-writing authority and is not promoted from this small generated set.

## Concrete safety changes

- **Institution-scoped LOCAL bank tokens**: equal digits at different institutions cannot create the same new token; missing institution requires review. Versioned v2 tokens do not silently merge/backfill historical v1 observations. Printed institution evidence is not verified bank ownership.
- **Mixed digital/scanned pages**: read text pages independently, add OCR evidence for unreadable pages when configured, and require review when page evidence remains unavailable. A second scanned conflicting total cannot be silently ignored.
- **Merged field labels**: a neighboring recognized label cannot become a party name or reference value. Every observed conflicting account value is redacted if repeated in public fields.
- **Incomplete line tables**: unresolved row layout/confidence/page evidence prevents aggregate line-sum fraud findings. A genuinely wrong fully read individual line or printed subtotal-plus-tax arithmetic remains independently checked.

The actual Thai both-engine API smoke originally emitted `math_inconsistent` after reading only one of two rows. After the final line-sum guard, the repeated request remains review with unresolved fields, and the false arithmetic finding disappears. [GLOBAL_HTTP_SMOKE.json](GLOBAL_HTTP_SMOKE.json) preserves before/after reasons. Its English pair has a compatible invoice but still requires review; Chinese/Thai pairs remain partial. HTTP 200 is not document acceptance.

## Validation and cleanup

- Final model-equipped environment: **92 passed**, 5 PyMuPDF/SWIG deprecation warnings, 18.54 seconds.
- Core/dev-only environment without Paddle/Ollama packages: **92 passed**, 6 dependency deprecation warnings, 16.54 seconds. The duplicate check environment is removed after verification.
- The case-insensitive account redaction guard was strengthened after the core-only run and the full model-equipped suite passed 92 again. Ruff check and format, dependency consistency and whitespace checks passed; timings are observations under uncontrolled host load.
- The original core synthetic evaluation still reports 196/196 header matches, injected twins with grounded values preserved, and all 10 seeded risk scenarios. Those simple fixtures do not supersede the harder corpus results above.
- All 80 corpus document bytes and the manifest regenerated identically, with disjoint family splits. Actual local API examples validate against OCR-local schemas and unchanged shared-compatible models.
- [Cleanup record](CLEANUP.json) lists removed service-owned temporary databases, logs, caches and the redundant verification environment. Superseded engine-attempt JSONs are consolidated into [selection notes](ENGINE_SELECTION_NOTES.md); reusable runtime/model assets and measured evidence remain.

## Next bounded work

1. Improve English column/label association and general line-table extraction using development examples, then evaluate new independent English documents before widening acceptance.
2. Validate Chinese field anchors, native date/currency rules and script policy as an explicit experimental adapter; keep unsupported results in review until demonstrated.
3. Obtain permitted independent documents and annotations. Determine acceptable review workload/latency from actual deployment needs; do not infer those targets from this synthetic sample.
4. Broaden benign/adversarial Qwen cases before promoting a prompt or changing model-alert policy. Keep candidate values independently grounded.
5. Obtain the owning team's decisions from [the consumer review packet](CONSUMER_REVIEW.md) before shared contract or registry changes.

Proxy-level total request limits, OS memory isolation, tenant/key/retention design, comprehensive QR/overlay handling, authoritative bank/financial ledgers and authenticity checks remain outside the completed local slice. No fraud probability calibration or live financing outcome is claimed.
