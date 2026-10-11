# OCR consumer review packet

Historical packet before the architecture increment. Use [the current handoff](HANDOFF.md) and [current examples](ARCHITECTURE_CONSUMER_EXAMPLES.json) for finding-scoped graphs, unsigned metadata and experimental Chinese extraction.

Status: prepared and locally schema-validated. Shared-contract adoption and registry migration await their owner. No shared schema edits, other-service edits, messages or remote Git actions were made.

## Current response semantics

| Trigger | `/ocr/extract` | `/ocr/verify` | Consumer behavior to agree |
|---|---|---|---|
| All required printed fields grounded | Shared-compatible invoice with OCR extensions | Invoice/PO checks with independent provenance | Inspect review reasons and risk details; HTTP 200 alone is insufficient |
| Required invoice field missing, conflicting or ambiguous | 422 | Typed partial evidence; `compatible_invoice: null` | Route to review; do not fabricate defaults or advance funds from partial fields |
| Grounded invoice/PO mismatch | Invoice may still be structurally compatible | `status: mismatch` with resolved evidence | Preserve the mismatch and reasons; do not interpret a model candidate as repair |
| Unknown comparison, unsupported language, unreadable page, unavailable model | Review flags, or 422 if required extraction fails | `status: review`, nullable values and unknown checks | Distinguish insufficient evidence from confirmed mismatch |
| Model alert or disagreement | Grounded values preserved, review flagged | Review reasons retained | Models have no field-writing or transaction authority |
| International v1 identity/precision limitation | Shared-compatible v1 may exist, with mandatory scope review | Review remains visible | Agree a versioned migration before relying on international registry identity |

The implemented mismatch status takes precedence over review status; both sets of reasons can coexist. A compatible invoice can still require review. A matched pair proves only consistency of the printed evidence inspected by this component.

## Concrete actual API examples

[CONSUMER_REVIEW_EXAMPLES.json](CONSUMER_REVIEW_EXAMPLES.json) contains actual multipart TestClient requests with separate ephemeral state and model-free PDF parsing:

- **Complete**: matched, compatible invoice exists.
- **Missing required field**: review, no compatible invoice.
- **Mismatch**: mismatch, compatible invoice exists but carries risk/review evidence.
- **International scope**: review even when headers/party evidence match, due to legacy fingerprint limitations.
- **Unsupported Chinese**: review, no compatible invoice; raw document fields are not supplied by Qwen.

[GLOBAL_HTTP_SMOKE.json](GLOBAL_HTTP_SMOKE.json) separately records three actual multipart invoice/PO scan pairs with local Paddle and Qwen enabled, using trusted English/Chinese/Thai recognizer profiles. These examples validate the OCR-local schemas and any non-null `compatible_invoice` against the unchanged shared schema. They do not exercise orchestrator/policy/wallet behavior.

The examples use synthetic parties, random ephemeral HMAC keys and temporary stores. Public evidence contains locations/hashes and scoped tokens, without account values. Document/observation IDs and fingerprints in the packet are illustrative run-specific values.

## Versioning and identity review

Legacy integration v1 remains unchanged: digit-only legal IDs/name fallback and two-decimal amount omit country/scheme. Concrete limitations include `AB-123` and `CD-123` reducing to the same identifier digits; equal IDs under different jurisdictions/schemes; and KWD `1.001`/`1.002` sharing a two-decimal canonical amount. Local semantic v2 separates scoped legal IDs and exact amounts; it does not replace the registry key automatically.

LOCAL banking tokens now use institution-scoped v2. Old v1 history is readable but does not merge with v2; no account identity or ownership authority is asserted from printed banking fields. Missing institution stays unresolved. This separate bank namespace is not an invoice registry migration.

## Decisions the owning team must record

1. Whether and how the pair endpoint becomes a consumer contract; who owns handling of null/unknown/review and incompatible extraction.
2. Whether review must block financing and how every reason reaches policy/UI. Existing policy thresholds are outside this OCR packet's implementation.
3. Versioned registry key fields, cross-version lookup policy, collision handling and migration evidence for international fingerprints.
4. Evidence retention, state/key ownership and access boundaries for deployment.

This packet is ready for review, not evidence that those decisions have been agreed.
