---
name: Specify document, state and graph regression acceptance checks
label: wayfinder:research
parent: ../map.md
status: resolved
assignee: codex-root
blocked_by:
  - independent-corpus.md
---

## Question

Which additional tests expose material correctness, privacy and persistence failures, and what bank-identity evidence is sufficient for a shared-account graph signal?

## Proposed test groups

| Area | Cases | Required behavior |
|---|---|---|
| Amounts and lines | Multiple SKUs, discounts, inclusive/exclusive VAT, rounding, JPY/KWD, ambiguous separators/dates | Exact Decimal comparisons with explicit currency/basis; unresolved evidence requires review |
| Independent PO | Missing/different references, changed parties, currencies, partial quantities | Match/mismatch/unknown follows independently extracted evidence; no assumed remaining allocation |
| Documents and models | Mixed digital/scanned pages, rotated input, malformed/oversized PDF/image, invisible text, metadata/annotation/QR instructions, invalid JSON and timeouts | Bounded failure, no document-driven action, no fabricated fields; unsupported inspection is documented |
| State | Concurrent same-key requests, changed bytes with same key, restart/replay, full history, persistence errors | One observation for the same request where supported; conflict and capacity errors are stable and do not corrupt history |
| Privacy | Bank values in evidence, exceptions, logs and API errors | No raw bank account or secret exposure |
| Graph negatives | Benign common account; same account digits at different banks/countries/schemes; correlated math/PO amount signals | No ungrounded company merge or spurious independent cluster; shared-account evidence stays contextual |

## Decisions required

- Current local-account tokens include country and scheme but not institution/routing identity. Determine whether supported documents provide trusted bank identity, or whether unresolved institution must limit signal interpretation. Specify token version/migration implications before implementation.
- Define concurrency semantics against the current SQLite implementation and available deployment context.
- Clarify total multipart request limits versus the per-file guard and process-level memory constraints. Do not claim the application guard alone bounds proxy/framework spooling.

## Evidence required to resolve

A prioritized test specification with concrete inputs and expected outcomes, plus decisions for identity and resource boundaries. Separate parser behavior, model-assisted injection quality and graph quality. Use scenario counts until enough independently labeled fraud/benign examples support precision/recall; do not calibrate a fraud probability from the existing seeded sequence.

## Resolution

See the [six-workstream reliability review](../../RELIABILITY_REVIEW.md). Measured outcomes and promotion limits are recorded separately from implementation authority.
