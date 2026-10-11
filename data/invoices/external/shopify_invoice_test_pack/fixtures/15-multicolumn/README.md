# Difficult multi-column layout

**Fixture ID:** `15-multicolumn`

SKU, barcode, qty, discount, tax and total in one dense table.

## Files

- `invoice.pdf`
- `invoice.png`
- `expected.json`

## Ground truth

See `expected.json`. Invoice `INV-2026-015` is dated 2026-08-15 in AED.

## Notes

- Line 2 includes a 10% line discount. Line tax amounts are shown in the table and must still reconcile to the invoice tax.

## Disclaimer

This document is synthetic. Names, TRNs, barcodes and amounts are invented for software testing. It is not a real supplier invoice and is not tax, customs or accounting advice.
