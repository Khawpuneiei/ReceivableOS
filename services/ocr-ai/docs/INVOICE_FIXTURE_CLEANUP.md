# Invoice fixture cleanup record

Date: 2026-10-10
Branch: `ocr/evidence-fraud-graph`

## Removed from the current branch tree

**38 tracked files** were removed:

- The 32 old flat OCR fixtures: the 13 English invoice variants and `en_po_clean.pdf`, their two English scan PNGs, the matching 13 Thai invoice variants and `th_po_clean.pdf`, and their two Thai scan PNGs. These were generated demo/regression copies, not customer files.
- The old root-level `labels.jsonl` and `demo_invoice.txt`.
- The four obsolete showcase assets: `northstar_invoice.pdf`, `northstar_invoice_preview.png`, `bluepeak_invoice.pdf`, and `bluepeak_invoice_preview.png`.

The old five PDFs under `data/invoices/demo/` were replaced in place with the source-derived polished sample set: a clean invoice, visible-injection case, inflated-total case, exact duplicate, and matching PO. The old file contents are gone from the current tree, while the paths used by the repository's demo and smoke commands still work.

## Why the flat set was removable

Tests and evaluation scripts now call the deterministic generators in temporary directories. The generated clean, partial, injected, mismatch, duplicate, and graph cases remain reproducible without keeping a second checked-in copy of every simple fixture. The polished source-based invoice and PO are the maintained visual examples.

## Intentionally retained evaluation data

- `data/invoices/reliability/`: the 80-document English-primary, Simplified Chinese experimental, and Thai synthetic OCR/PO corpus plus its manifest. OCR tests, layout evaluation, and consumer-review examples still use these files directly.
- `data/invoices/external/shopify_invoice_test_pack/`: 15 attributed fictional scenarios with their PDF/PNG examples, source labels, checksums, and CC BY 4.0 license. The extraction coverage test still uses this external challenge data.
- `data/invoices/fonts/`: the Noto Thai font and OFL notice required to generate temporary Thai regression fixtures.

These retained corpora are active evaluation inputs, not superseded showcase invoices. Deleting them would remove Chinese/Thai and international layout coverage; deleting the external pack would also remove its preserved attribution/license metadata. A separate request can remove them after replacement evaluation inputs and references exist.

## Git history

The files above are removed from the branch's current tree. Earlier commits still contain their prior versions; this cleanup does not rewrite Git history.
