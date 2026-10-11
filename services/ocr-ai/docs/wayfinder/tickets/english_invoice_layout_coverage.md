---
name: Improve English invoice anchors and unit-aware line extraction from external challenge findings
label: wayfinder:task
parent: ../map.md
status: resolved
assignee: codex-root
blocked_by: []
updated: 2026-10-10
---

## Question

Can OCR-owned extraction safely cover common English invoice role labels and explicit six-column item tables exposed by the publisher-provided challenge pack, while preserving source grounding, exact currency/date interpretation and abstention for unsupported concepts?

The original parser baseline is [preserved in the external evaluation](../../EXTERNAL_INVOICE_EVALUATION.json): 29/232 header fields and 0/330 line fields, with no parser/OCR exceptions. Its evaluator used the wrong publisher SKU key and did not score units. A source-span inspection of `01-simple-english` shows readable text such as `Invoice:`, `Date:`, `Bill to:`, a six-column `SKU / Description / Qty / Unit / Price / Total` table, and summary rows whose label and `AED` value share one visual row. These are role/layout gaps, not established character-recognition errors.

## Route and scope

Improve exact English role anchors and table parsing using independent source spans, with page/source/geometry checks and explicit ambiguity abstention. Preserve raw currency evidence and require a validated declared ISO currency before accepting an amount that carries a currency code. Add the line unit as OCR-local evidence and compare quantities only when units are safely comparable; do not change shared schemas or consumer services. Keep discounts, freight, duty, Arabic and unsupported tax structures as review/unknown until represented and validated.

After changes, rerun relevant regressions and the external pack. Reclassify that pack as development data; it no longer qualifies as a holdout. Record per-field and line results by source format, parser/OCR route and unresolved review reasons. Do not infer global support or fraud accuracy from this publisher-authored synthetic set.

## Resolution

Implemented locally on `ocr/evidence-fraud-graph`. Exact English role anchors now cover invoice number/date, bill-to/customer, vendor and spatial summary labels. The deterministic table parser accepts explicit five-column rows and six-column rows with unit, closes the table at financial summaries, and emits `LINE_LAYOUT_UNSUPPORTED` for recognized but unsupported table shapes. Currency-bearing financial values require an explicit matching ISO currency; unlabeled seller letterhead remains raw and ambiguous. Unmodeled discount/freight/duty components trigger review and suppress misleading arithmetic accusations.

Line `unit` is explicit OCR-local evidence. `/ocr/verify` requires both sides to show a matching normalized unit before quantity or unit-price comparison. Missing unit yields unknown checks; differing units mismatch and quantity/price stay unknown. No conversion is inferred. The consumer handoff is `invoice-po-rules-v3`, with `respect_unknown_line_unit_checks` required. Shared schemas and downstream services were not changed. ADR [0006](../../adr/0006-explicit-line-unit-comparison.md) records this boundary.

The corrected external challenge rerun evaluated 29 inputs in 222.097 seconds with zero parser/OCR failures: 180/232 header fields (77.59%), 322/396 line fields, and 56/66 expected rows observed. Exact-line documents: English PDF 9/11, English PNG 8/10, pure Arabic 0/2, dense Arabic/English 0/6. No document had all header fields because the seller letterhead remains role-ambiguous. These publisher-authored synthetic labels are development data, not an independent holdout or global performance estimate. The current four-scan generated model test is Paddle 24/28 and Qwen candidate 28/28 with language-matched Paddle models; English ties at 14/14 and two Thai scans favor Qwen 14/14 to 10/14. Single-run latency/cache conditions are uncontrolled. Qwen’s candidate role remains unchanged.

Validation: `138 passed` with five existing PyMuPDF/SWIG deprecation warnings; Ruff check/format, compileall and `git diff --check` pass. Independent licensed holdout selection, Arabic/Chinese layout coverage, consumer-owner agreement, and fraud calibration remain open.
