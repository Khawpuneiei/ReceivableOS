---
name: Prototype English column and table evidence assignment
label: wayfinder:prototype
parent: ../map.md
status: superseded
assignee: codex
blocked_by: []
---

## Question

Which bounded spatial/anchor approach recovers English panel fields and printed line tables without attaching neighboring values to the wrong role?

Use current development examples to compare anchor-based segments and table parsing. Require field/line source locations, exact Decimal values and ambiguity abstention. Do not tune to heldout reference numbers or filenames. Record recognition versus role-assignment failures and evaluation-code hashes.

Resolution requires a prototype report, negative cases, coverage/review/latency tradeoffs and an implementation decision. Live promotion needs independent-document validation; the existing generated holdout alone cannot establish global vendor support.

The latest user-authorized [architecture task](architecture-upgrade.md) supersedes this spike for bounded MVP anchors and an explicit table schema. [Measured results](../../ARCHITECTURE_VALIDATION.md) do not satisfy independent/global-vendor promotion criteria; source selection remains open.
