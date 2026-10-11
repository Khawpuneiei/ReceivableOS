# Kuwait KWD invoice

**Fixture ID:** `07-kuwait-kwd`

Three-decimal values with no assumed VAT line.

## Files

- `invoice.pdf`
- `invoice.png`
- `expected.json`

## Ground truth

See `expected.json`. Invoice `INV-2026-007` is dated 2026-08-07 in KWD.

## Notes

- No VAT line is printed. Extractors must not invent a tax amount.
- Keep three decimal places for KWD.

## Disclaimer

This document is synthetic. Names, TRNs, barcodes and amounts are invented for software testing. It is not a real supplier invoice and is not tax, customs or accounting advice.
