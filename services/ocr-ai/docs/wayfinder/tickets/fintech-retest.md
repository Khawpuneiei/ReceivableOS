---
name: Retest financial comparisons and enforce consumer review invariants
label: wayfinder:task
status: resolved
assignee: codex
updated: 2026-10-10
---

## Question

Which financial discrepancies can disappear between independent invoice/PO checks and the shared-compatible consumer projection?

## Route and scope

The user authorizes another test/fix increment and continuing branch updates. Keep shared contracts, transaction authority and other services unchanged. Test real synthetic multipart inputs first: one minor-unit payable discrepancy (USD/JPY/KWD), offsetting line prices with unchanged header totals, mixed under/over PO quantities, and zero invoice face value. Preserve all resolved mismatches, exact printed commercial-price comparisons and review propagation. Do not label zero-value documents or ordinary rounding as fraud without evidence. Follow diagnosing-bugs and record the red/green loop.

Baseline: 113 tests pass, but the added financial cases expose gaps. Additional probes exposed numerical bounds/context and minor-unit internal arithmetic review gaps. [New regressions](../../../tests/test_fintech_review.py) and [the retest report](../../FINTECH_RETEST.md) hold actual evidence. Broader model/corpus reruns validate compatibility; generated data does not establish production accuracy.

## Resolution

Thirteen cases reproduced failures before their corresponding fixes; five additional response guards verify internal consistency. The final suite passes 131 tests. [Exact financial comparison and review](../../adr/0005-exact-financial-comparison-and-review.md) defines comparison-v2, SKU-specific partial uncertainty, preserved over-order mismatches, mandatory review propagation, bounded exact arithmetic and context-independent local identity. Registry-v1 remains unchanged. Paddle/text header results remain English 336/336, experimental Chinese 112/112 and Thai 99/112; all three both-engine API pairs require review and Qwen's benign false alerts persist. Mock transport compatibility passes; consumer adoption and independent document validation remain open owner work.
