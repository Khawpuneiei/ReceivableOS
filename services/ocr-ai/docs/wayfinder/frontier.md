# Reliability planning frontier

Parent: [Establish evidence for OCR and fraud reliability beyond the demo templates](map.md).

The six user-authorized workstreams were exercised on 10 October 2026. The 11 October follow-up resolved public-source selection and prepared the Policy/orchestrator owner handoff. [The workstream review](../RELIABILITY_REVIEW.md) links measurements, fixes, regressions and limitations.

The latest source-derived invoice, legacy cleanup, and fraud validation task is resolved; see [the verification report](../FRAUD_VALIDATION.md) and [cleanup record](../INVOICE_FIXTURE_CLEANUP.md). The 80-document reliability corpus and the attributed external challenge fixtures remain active evaluation inputs.

## Current external handoff

[Agree consumer review semantics and international fingerprint migration](tickets/consumer-contract.md) is awaiting owner review. Local examples and the concrete packet are prepared; no shared change or owner agreement is implied.

[Policy integration handoff](../POLICY_INTEGRATION_HANDOFF.md) records the fixed-approve stub, two observed hard-guard violations, the OCR/Policy fraud-code naming mismatch, a guard matrix and the proposed versioned evidence bundle. A separate PM `contract:` review and Policy implementation are required; this OCR branch does not change those owners' files.

The external synthetic challenge set is development data. [Improve English invoice anchors and unit-aware line extraction from external challenge findings](tickets/english_invoice_layout_coverage.md) is resolved locally with corrected 29-input evaluation and the v3 unit-aware comparison handoff.

## Architecture increment and remaining frontier

| Priority | Ticket | Type | Required outcome |
|---|---|---|---|
| Independent holdout | [Acquire permissioned invoice evidence and freeze the independent holdout](tickets/permissioned-holdout.md) | task | Permissioned English invoices plus Chinese/Thai and adjudicated fraud labels where available |

The source-selection research is resolved in [DATASET_ACCESS_AND_HOLDOUT.md](../DATASET_ACCESS_AND_HOLDOUT.md). DocILE needs an access token/terms review; XFUND is forms with non-commercial share-alike terms; SROIE is receipts whose dataset rights need confirmation. No external corpus was downloaded or placed in Git.

The user subsequently authorized [Upgrade spatial extraction and versioned fraud handoff](tickets/architecture-upgrade.md), now implemented and measured. It supersedes the English/Chinese spike proposals for bounded anchors and explicit tables; general vendor layouts, native Chinese forms and independent validation remain open scope. Qwen's prompt stays unchanged and candidate authority stays unchanged. Deployment targets and consumer adoption remain owner decisions.

[Retest financial comparisons and enforce consumer review invariants](tickets/fintech-retest.md) remains resolved with 131 tests as historical evidence. The new v3 local rules are recorded in the resolved English layout ticket. Independent source selection and consumer-owner contract review remain open.

Bank ownership verification remains an external dependency: Security/Policy/Wallet must select an authorized bank or KYB provider and approve legal basis, consent and test credentials. OCR's masked account observations and HMAC graph tokens are correlation evidence only.
