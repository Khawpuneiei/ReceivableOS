---
name: Agree consumer review semantics and international fingerprint migration
label: wayfinder:grilling
parent: ../map.md
status: awaiting_owner
assignee: codex-root
blocked_by: []
---

## Question

What must downstream consumers do with typed partial results, model disagreement and international identity/fingerprint evidence, without changing the existing shared extraction contract silently?

## Review packet to prepare

- Start with the existing [OCR-local contract proposal](../../CONTRACT_PROPOSAL.md). Show complete, missing, ambiguous and conflicting examples, including the current Thai scan result.
- Explain `/ocr/extract` required-field failure versus `/ocr/verify` typed partial evidence; specify consumer handling of review/unknown outcomes before advertising the pair endpoint as integrated.
- Document why legacy v1 fingerprints retain compatibility while local v2 uses scoped identities and exact monetary values. Assess collision and migration cases with concrete examples.
- Show graph scores as uncalibrated evidence signals and the policy threshold interaction. No implicit financing approval, remaining PO allocation or proven fraud.

## Evidence required to resolve

A concrete packet and recorded decision from the shared-contract/consumer owner about semantics and any migration route. Preparing local documents is unblocked; changing shared schemas or another service is outside OCR ownership. This ticket does not authorize sending messages, opening a PR or editing those components.

## Local handoff

The [consumer review packet](../../CONSUMER_REVIEW.md) and actual API examples are prepared. No owner agreement, shared changes or contact is implied.
