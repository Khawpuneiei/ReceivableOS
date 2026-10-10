---
status: implemented-locally
date: 2026-10-10
---

# Require matching observed units before comparing line quantities and unit prices

The OCR-local `LineExtraction` records an observed line unit with the same source evidence as the other row values. `/ocr/verify` emits a `LINE_UNIT` check for each aligned SKU. The unit must be present in both documents and match after Unicode NFKC normalization, whitespace compaction and case folding before quantity or unit-price comparisons are meaningful.

Missing units produce `unknown` unit, quantity and unit-price checks. Different units produce a unit mismatch and leave quantity/unit-price comparisons unknown. No synonym dictionary, pack conversion, tax conversion or unit conversion is inferred. The OCR-local comparison version is `invoice-po-rules-v3`.

The shared `ExtractedInvoice` schema and other services remain unchanged. The compatible single-invoice projection cannot make a cross-document unit claim; consumers must review the OCR-local pair checks. Adoption of the pair contract remains pending its owner review.
