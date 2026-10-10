# USD supplier invoice for an AED merchant

**Fixture ID:** `08-usd-for-aed`

Explicit foreign currency for FX-policy tests.

## Files

- `invoice.pdf`
- `invoice.png`
- `expected.json`

## Ground truth

See `expected.json`. Invoice `INV-2026-008` is dated 2026-08-08 in USD.

## Notes

- Invoice currency is USD. Do not silently treat amounts as AED.
- Preserve the original currency in the audit trail and apply an explicit FX policy.

## Disclaimer

This document is synthetic. Names, TRNs, barcodes and amounts are invented for software testing. It is not a real supplier invoice and is not tax, customs or accounting advice.
