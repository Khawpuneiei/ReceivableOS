# Exact financial comparisons and consumer review invariants

Status: accepted for the OCR-local MVP, 10 October 2026. Implements [Retest financial comparisons and enforce consumer review invariants](https://github.com/Khawpuneiei/ReceivableOS/blob/ocr/corpus-evidence/services/ocr-ai/docs/wayfinder/tickets/fintech-retest.md).

## Evidence

The original 113 tests passed, but independent rendered invoice/PO uploads exposed disappearing discrepancies: a one-minor-unit printed amount difference was matched; partial invoicing suppressed another SKU's over-order quantity and an above-order payable; offsetting unit prices produced pair mismatch without consumer review. Zero face value also left single extraction without review. Additional probes reproduced an oversized-number server exception, context-dependent local semantic identity and silent minor-unit internal arithmetic discrepancies. Thirteen new cases failed before their respective fixes; five further tests exercise inconsistent response rejection.

## Decision

`invoice-po-rules-v2` compares resolved printed amounts and unit prices exactly, on the same declared currency and tax basis. Decimal equality accepts equivalent formatting such as `100` and `100.00`; no exchange rate or rounding estimate changes source facts. Unit prices with unknown/different tax basis stay unknown.

Under-order quantity needs trusted allocation evidence for that SKU. It does not suppress another SKU's resolved over-order quantity. Lower/equal header amounts remain allocation-unknown for partial invoices; a printed amount above the full order remains a mismatch. Uploads cannot establish delivery, cumulative usage or remaining PO capacity.

Every resolved pair mismatch generates a review reason, requires handoff review and caps shared-compatible confidence below the configured 0.80 threshold. The response model rejects downgraded mismatches, high-confidence unmatched projections, inconsistent review state, reordered/changed document hashes and inconsistent observation IDs. These checks prevent service output inconsistencies; they do not authenticate an external response.

Zero invoice face value requires review without a fraud accusation. Internal line/subtotal/tax discrepancies within one currency minor unit require rounding review; larger discrepancies retain the existing arithmetic finding. The difference between printed cross-document facts has no such tolerance.

Financial observations are bounded to 64 source characters, 28 coefficient digits and 12 decimal places; scientific notation is unsupported. Oversized/unsupported required amounts remain unresolved and single extraction returns 422. Validation uses 64-digit local arithmetic precision, sufficient for products of bounded coefficients and sums of at most 500 lines. Local semantic-v2 amount canonicalization strips fractional trailing zeros without context-dependent rounding. Shared registry-v1 canonicalization remains unchanged; historical international/two-decimal limitations still require owner migration.

## Consequences

More discrepancies require explicit review; no acceptance, tax compliance, calibrated fraud probability or financing authority is inferred. Existing shared schemas and other service source are unchanged. The handoff gains a defaulted optional comparison version; downstream owners must recognize it when adopting the local packet. Historical evaluation artifacts retain their original source versions. Current results are linked from [the retest report](https://github.com/Khawpuneiei/ReceivableOS/blob/ocr/corpus-evidence/services/ocr-ai/docs/FINTECH_RETEST.md).
