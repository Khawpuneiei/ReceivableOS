---
name: Establish evidence for OCR and fraud reliability beyond the demo templates
label: wayfinder:map
status: implemented
updated: 2026-10-11
---

## Destination

Upgrade source-grounded invoice/PO extraction and explainable fraud graphs inside the OCR-owned module. Deliver tested, versioned consumer handoff evidence on our branch, ready for later Agent Wallet + Cybersecurity integration.

## Notes

- This map follows the completed local implementation, not a restart of it. Use the [frontier](frontier.md) to find open child tickets; ticket metadata is the local tracker.
- Current outcomes for all six authorized workstreams are recorded in [the reliability review](../RELIABILITY_REVIEW.md); generated-source limits and the pending consumer owner decision remain explicit.
- The user authorized execution of all six workstreams on 2026-10-10, with English primary, Chinese experimental and Thai secondary. Claim a ticket by setting its assignee before investigating it. Close it with a linked resolution artifact; do not treat a proposed experiment as a completed result.
- Keep branch `ocr/evidence-fraud-graph`. Edit only `services/ocr-ai/**`, OCR-owned `data/invoices/**`, and optionally `docs/05-ocr-ai.md`. The latest user request on 2026-10-10 authorizes architecture implementation and updating this remote branch; it supersedes the earlier restriction on remote Git actions. Never push main or merge another owner's work.
- Execution override: claim and implement [Upgrade spatial extraction and versioned fraud handoff](tickets/architecture-upgrade.md), then record actual verification. Apply codebase-design at the layout and graph seams. Existing consumer agreement remains pending.
- The latest user request authorizes [Retest financial comparisons and enforce consumer review invariants](tickets/fintech-retest.md), including fixes, tests and continuing updates to the same branch. Apply diagnosing-bugs to demonstrated failures; financial discrepancies remain source evidence, not transaction authority.
- The latest request authorizes [Create source-derived invoice samples and consolidate OCR/fraud verification](tickets/source-derived-invoice-and-fraud-validation.md), including a precise cleanup pass. Preserve the reliability corpus and attributed third-party fixtures while they remain active regression evidence; list exact legacy files before deleting them.
- The 2026-10-11 follow-up completes OCR-owned handoff preparation for Policy/orchestrator and public-dataset access research. It does not authorize changing `services/policy-ai/`, `services/orchestrator/`, `shared/`, bank integrations, or another owner's code; see [Policy integration handoff](../POLICY_INTEGRATION_HANDOFF.md) and [dataset access/holdout decision](../DATASET_ACCESS_AND_HOLDOUT.md).
- Evaluation prioritizes English, with a separately reported Chinese experimental track and Thai secondary track. Technical documents/code are English; user explanations are Thai. Apply Wayfinder; use grilling for decisions that require the user or a contract owner, rather than reopening settled choices.
- Baseline evidence: [synthetic evaluation](../EVALUATION.json), [four-scan engine benchmark](../ENGINE_BENCHMARK.json), [both-engine HTTP smoke](../HTTP_SMOKE.json). The final reliability validation passed 92 service tests in both model-equipped and core-only environments; that count is not a measure of document coverage.
- The latest engine rerun covers only four generated scans with language-matched Paddle recognizers: Paddle matches 24/28 scalar fields and Qwen candidates 28/28. English ties at 14/14; Thai is 10/14 versus 14/14 on two fixtures. One-run timings had uncontrolled cache/background state. Separate HTTP smoke cases still produce Qwen false injection alerts and amount disagreements; do not generalize to unseen documents.
- Proposed corpus sizes and performance targets in child tickets are planning suggestions, not measured results or agreed production requirements. Report unknowns explicitly; never accept an unsupported critical financial value merely to improve coverage.

## Decisions so far

- [OCR-local pair verification boundary](../adr/0001-ocr-local-verification-boundary.md): preserve shared extraction compatibility and represent incomplete pair evidence locally.
- [Local PaddleOCR and Qwen-VL experiment](../adr/0002-local-paddle-and-qwen.md): use both local engines, with document evidence governing accepted fields.
- [Bounded observed history](../adr/0003-bounded-observation-history.md): observations and graph signals remain service-local and confer no financing authority.

- [Define an independent invoice and PO evaluation corpus](tickets/independent-corpus.md): English-primary synthetic stress design is implemented, with independent-source validation still required.
- [Diagnose Thai scan recognition and field assignment](tickets/thai-scan-diagnosis.md): missing tone marks and row geometry explain observed failures; English columns/tables remain the primary extraction gap.
- [Measure Qwen candidate reliability and alert errors](tickets/qwen-reliability.md): retain candidate-only authority; the prompt variant fails benign-alert checks and is not promoted.
- [Validate evidence-grounded recovery for missing Thai fields](tickets/grounded-recovery.md): measured 14 additional grounded fields on four generated Thai scans; keep the prototype isolated.
- [Specify document, state and graph regression acceptance checks](tickets/regression-acceptance.md): institution-scoped tokens, mixed-page review, label/redaction guards and incomplete-table sum checks pass local regressions.
- [Upgrade spatial extraction and versioned fraud handoff](tickets/architecture-upgrade.md): bounded spatial/table extraction, experimental Chinese anchors, typed finding-scoped graph and unsigned handoff are implemented; 113 service tests and mock transport checks pass.
- [Retest financial comparisons and enforce consumer review invariants](tickets/fintech-retest.md): exact comparison-v2, preserved over-order discrepancies, numerical bounds/context stability and mandatory review pass 131 regressions; this count is historical after the v3 increment.
- [Improve English invoice anchors and unit-aware line extraction from external challenge findings](tickets/english_invoice_layout_coverage.md): explicit English anchors/tables, conservative unsupported-layout review, OCR-local units and comparison-v3 are implemented; corrected development-set results are recorded, with independent validation still open.
- [Create source-derived invoice samples and consolidate OCR/fraud verification](tickets/source-derived-invoice-and-fraud-validation.md): replaced the old flat demo set with polished source-derived invoice/PO examples, removed 38 obsolete files, moved regression generation to temporary directories, and verified the Fraud API. Active reliability and attributed external corpora remain.
- [Select permitted independent English-first evaluation documents](tickets/independent-source-selection.md): research resolved; DocILE access requires a token, XFUND is a non-commercial Chinese form set rather than invoice ground truth, and SROIE is a receipt set whose dataset terms need separate confirmation. No external source was ingested.

## Not yet specified

- Representative deployment traffic, expected concurrency and acceptable latency/review workload. These determine later performance targets.
- Availability of independently sourced, licensed and privacy-safe Thai invoice/PO examples. Generated layouts alone cannot establish real-world reliability.
- Approved access to DocILE or another English business-document corpus, plus human-annotated native Chinese/Thai invoice holdouts and adjudicated invoice-fraud cases.
- An approved bank/KYB verification provider, legal basis/consent and test credentials for ownership verification; observed OCR account text alone is never proof of ownership.
- PM contract review and Policy/orchestrator adoption of the OCR evidence handoff; the current Policy stub still violates two hard guards.
- Production tenancy, retention and HMAC rotation requirements, if this component later moves beyond the current local MVP. They need deployment context before actionable tickets.

## Out of scope

Shared-schema or other-service implementation, wallet/credit decisions, live customer ingestion, cloud OCR migration, model fine-tuning, GNN/graph databases, and claims of calibrated fraud probability or production readiness.
