---
name: Validate evidence-grounded recovery for missing Thai fields
label: wayfinder:prototype
parent: ../map.md
status: resolved
assignee: codex-root
blocked_by:
  - independent-corpus.md
  - thai-scan-diagnosis.md
  - qwen-reliability.md
---

## Question

Can a Qwen candidate help recover a missing field while deterministic checks establish its source location and correct field role?

## Prototype boundary

- Build a disposable experiment, not a change to the live API. Search independently obtained OCR spans or a separately verified crop for the candidate and its field anchor.
- Preserve page/bounding-box provenance and distinguish supplier/buyer, issue/due date, subtotal/grand total and currency. A matching number somewhere on the page is insufficient.
- Multiple plausible locations, unsupported dates, contradictory text, currency conflicts or values visible only in the model answer must remain unresolved/review.
- Include negative cases where Qwen confidently selects a wrong subtotal or party, and cases where the authoritative OCR cannot see the candidate at all.

## Evidence required to resolve

A linked prototype artifact and report showing accepted fields with correct value, role and source evidence. Proposed safety gate: zero silently accepted wrong critical fields on the frozen evaluation set; failures block promotion. This finite-set gate does not imply zero production errors. Report coverage/review/latency tradeoffs, then decide whether to promote, redesign or discard the approach.

## Resolution

See the [six-workstream reliability review](../../RELIABILITY_REVIEW.md). Measured outcomes and promotion limits are recorded separately from implementation authority.
