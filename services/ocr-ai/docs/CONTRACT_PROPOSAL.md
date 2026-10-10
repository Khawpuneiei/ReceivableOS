# Proposed independent invoice–PO consumer contract

Status: implemented locally for review, not adopted by shared schemas or another service. The user accepted the Q2 partial-result plan. Existing `/ocr/extract` keeps multipart `file` and a response compatible with `shared.schemas.ExtractedInvoice`; unresolved required fields return 422. Optional OCR-owned extensions carry evidence and review details.

The current optional handoff declares `comparison_version: invoice-po-rules-v3`. Exact printed monetary/price comparisons require resolved matching currency and tax bases; quantity and unit price also require matching observed line units. Missing units yield unknown checks; different units mismatch without numeric quantity/price comparisons. Partial allocation uncertainty does not erase resolved over-order quantities or above-order payables. Any mismatch requires review and compatible confidence below 0.80. Both hashes, observation ID, pair status and handoff review must agree; these are internal consistency checks, not service authentication. See [financial semantics](adr/0005-exact-financial-comparison-and-review.md) and [unit semantics](adr/0006-explicit-line-unit-comparison.md).

`POST /ocr/verify` accepts required multipart `invoice_file` and `po_file`, each independently validated and parsed. The local `ocr-local-v1` result contains:

| Field | Meaning |
|---|---|
| `status` | `matched`, `review`, or `mismatch`; grounded mismatch takes precedence |
| `invoice`, `purchase_order` | Typed partial document extractions with independent SHA-256 hashes |
| `compatible_invoice` | Nullable existing shared invoice shape when required fields are grounded |
| `checks` | Field, status `match/mismatch/unknown`, rule code, both values and independently scoped evidence refs |
| `review_reasons` | Missing/ambiguous/conflicting/unsupported evidence and contextual limitations |
| `fraud_details` | Typed deterministic risk findings, evidence metadata, reasons, version and tokenized paths |
| `fraud_graph`, `handoff` | Additive finding-scoped `ocr-graph-v1` and unsigned `ocr-handoff-v1`; see [current adoption packet](HANDOFF.md) |

Each field observation has nullable `value`, bounded `raw_value`, `status`, confidence and evidence references. Present observations must have nonempty source evidence. Each reference has stable ID, document hash, page, source kind, confidence and bbox/text span. Public references have no source text or bank accounts. Unknown checks can lack one side's evidence; a resolved match/mismatch must have evidence from both uploads.

Checks cover PO reference, scoped supplier/buyer identifiers plus names/countries/schemes, currency, tax basis, subtotal/tax/total, matched SKU descriptions, line units, quantities and unit prices. Missing SKU alignment or unit evidence, low-confidence fields, unlike currencies/bases and unknown partial-invoice allocation produce unknown. The shared single-invoice schema has no unit field; cross-document unit checks remain local to `/ocr/verify` until owner review. There is no FX or unit conversion, historical PO substitution, remaining-order capacity claim, delivery/acceptance evidence, or authenticity verdict.

Optional `Idempotency-Key` scopes history to route and upload bytes. HTTP errors: 413 limits, 415 format/MIME/signature, 422 unreadable or unresolved required extraction, 409 conflicting retry bytes, 429 processing capacity, 503 missing secrets/history capacity. `/health` is unchanged liveness.

A separate smallest contract PR should agree consumer handling of nullable values, evidence availability/retention, unknown checks, review semantics, and the international v2 fingerprint namespace. Legacy v1 rounds to two decimals and omits country/scheme; its name fallback must never serve graph entity resolution. Keep existing registry keys until an explicit versioned migration is reviewed. No integration or remote PR was created here.
