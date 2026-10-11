---
name: Upgrade spatial extraction and versioned fraud handoff
label: wayfinder:task
status: resolved
assignee: codex
updated: 2026-10-10
---

## Question

How can the OCR-owned architecture handle independently uploaded invoice/PO columns and tables and expose auditable fraud relationships for later wallet/security integration without changing shared contracts?

## Resolved implementation route

Use deterministic source geometry for role assignment, retaining conflicting observations and abstaining on neighboring labels. Extract explicit five-column tables only when their header defines the row schema; partial tables remain reviewable. Add exact Simplified Chinese aliases experimentally with ISO dates and explicit ISO currency/locale, without guessing native forms. Qwen remains candidate-only.

Build typed invoice/company/token graphs once behind a graph module; rules use the same graph. Return only the current observation and finding-linked nodes/edges, with evidence locations, versioned extraction/rule metadata and a consumer handoff declaring no financial authority. Preserve `/ocr/extract` shared required fields and `/ocr/verify` partial semantics. No new runtime dependencies or other-service edits.

Acceptance: regressions for column ambiguity, cross-page/source pairing, hidden/instruction text, table completeness, Chinese experimental review, graph isolation and handoff grounding; rerun the 80-document corpus with staged Paddle profiles, line evaluation, service tests and core mock integration. Record measured limitations before committing and pushing only `ocr/evidence-fraud-graph`.

## Resolution

[Architecture](../../ARCHITECTURE.md) and [validation](../../ARCHITECTURE_VALIDATION.md) record the implemented route. Seven-field matches are en 336/336 (16 correct nulls), zh 112/112 experimental, th 99/112; line tuples en 88/88, zh 28/28, th 26/28. No wrong non-null measured headers. The full suite passes 113; current mock transport remains compatible. [Handoff](../../HANDOFF.md) awaits consumer owners; no signing/chain authority or independent-vendor validation is claimed.

This bounded MVP increment supersedes the separate English/Chinese spike proposals for exact anchors and the explicit table schema. Their wider independent-vendor and native financial-form promotion criteria remain unmet; those open questions move into source selection and follow-on language scope rather than being reported as completed production support.
