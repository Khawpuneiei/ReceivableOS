---
name: Acquire permissioned invoice evidence and freeze the independent holdout
label: wayfinder:task
parent: ../map.md
status: open
assignee: null
blocked_by:
  - Partner/Finance-approved access to representative documents
  - Dataset-specific reuse terms and privacy approval
---

## Destination

Evaluate a frozen, independently sourced English-first OCR holdout, with separate Chinese and Thai invoice/PO tracks when permissioned examples are available. Build a distinct adjudicated fraud set before making any real-world fraud precision/recall claim.

## Inputs required

- A documented source, named data owner, reuse/retention terms and privacy basis for each corpus.
- Human-checked normalized invoice/PO fields, line-item groups, source-page/bbox evidence and explicit missing/ambiguous labels.
- Supplier/template-family and time metadata to prevent family leakage; preserve duplicate/revision variants together.
- For fraud only: adjudicated positive and benign near-miss cases with reason, typology, time and reviewer outcome. OCR anomalies and synthetic injected labels do not count as confirmed fraud.

## Acceptance

- Freeze the model, prompt, normalizer and threshold before opening the holdout; never tune on holdout results.
- Report per-language, document/input type, supplier family and field: exact normalized match, precision/recall, wrong-present rate, abstention/review rate, line-item tuple F1 and evidence-location validity with sample counts and confidence intervals.
- Report injection recall and benign false-alert rates separately from OCR accuracy and separately for each detection mechanism.
- Report fraud precision/recall and workload by adjudicated typology only. Keep synthetic scenario performance labeled as regression coverage.
- Keep raw documents and PII outside Git unless explicit redistribution rights allow it; commit only sanitized manifests/reports with reproducible hashes.

## Current blockers

DocILE official downloads require an access token and dataset terms review. XFUND is a CC BY-NC-SA human-labeled form set, not invoices. SROIE is a receipt set and linked-data terms need separate verification. No permissioned Thai invoice holdout or adjudicated B2B invoice-fraud cases are currently available to OCR.

See [source/access review](../../DATASET_ACCESS_AND_HOLDOUT.md) and [research findings](../../RESEARCH_AND_NEXT_STEPS.md).
