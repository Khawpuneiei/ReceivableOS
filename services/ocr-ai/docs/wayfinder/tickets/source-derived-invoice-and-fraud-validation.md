---
name: Create source-derived invoice samples and consolidate OCR/fraud verification
label: wayfinder:task
status: resolved
assignee: codex-root
updated: 2026-10-10
---

## Destination

Create a polished invoice and companion PO from the existing fictional Siam Fresh Pack / Mekong Basket fixture data, then verify the current OCR and fraud behavior through repeatable tests. Prepare a precise cleanup manifest for superseded invoice files.

## Scope and rules

- Keep the work on `ocr/evidence-fraud-graph` and within OCR-owned paths.
- Reuse only fields documented as synthetic; visibly label generated PDFs as fictional samples.
- Verify the PDFs visually and through extraction before declaring them complete.
- Run the OCR service suite and explicitly report fraud scenario coverage, output, and limits.
- The user authorizes deleting old invoice files. Classify exact paths before removal. Preserve active reliability inputs and attributed external challenge fixtures unless they are safely replaced and tests remain reproducible; explain any active-data retention in the cleanup record.
- Do not rewrite Git history. A working-tree deletion removes current files but does not erase prior committed versions.

## Findings at claim

Existing fraud API regressions cover exact and semantic duplicates, near-duplicate revisions, shared account relationships, suspicious clusters, account changes, PO amount/currency mismatches, evidence path resolution, idempotency, persistence and bank-data redaction. They are spread across `tests/test_pipeline.py`, `tests/test_normalize_graph.py`, and `tests/test_fintech_review.py`; the task is to run and report them together, then close any concrete gap found.

The flat synthetic inputs and `data/invoices/demo/` have live references. `data/invoices/reliability/` and `data/invoices/external/shopify_invoice_test_pack/` are separately documented evaluation corpora with active tests and provenance.

## Resolution

Created a polished invoice and matching PO from the legacy Siam Fresh Pack / Mekong Basket synthetic records. Corrected the source fixture's inconsistent `inclusive` tax-basis label to `exclusive` because the printed amounts add as subtotal plus VAT. Replaced all five demo PDFs with the polished clean/injection/inflated/duplicate/PO set and removed 38 obsolete flat or superseded showcase assets. Regression/evaluation fixtures are now generated in temporary directories. Preserved the active 80-document reliability corpus, the attributed 15-scenario external challenge pack, and the licensed Thai font.

Validation: `149 passed`, full Ruff check and format check pass, `git diff --check` passes, and the updated synthetic evaluation matches 10/10 fraud sequences. A local PaddleOCR preview run extracted the source-derived English invoice fields and line item; the `/ocr/verify` scan-invoice/PDF-PO request returned `matched`, with no mismatch or review reason and no raw sample bank account disclosure. See the [fraud validation report](../../FRAUD_VALIDATION.md) and [invoice cleanup record](../../INVOICE_FIXTURE_CLEANUP.md).
