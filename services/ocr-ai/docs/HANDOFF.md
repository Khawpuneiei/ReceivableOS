# Agent Wallet and Cybersecurity review packet

Status: ready for owner review; no owner agreement or downstream adoption claimed.

The current local handoff declares `comparison_version: invoice-po-rules-v3`. It requires matching observed line units before comparing quantity or unit prices; absent units are unknown, different units mismatch, and no conversion is attempted. The earlier `invoice-po-rules-v2` financial retest remains historical. Every resolved mismatch requires review, and unmatched shared projections carry confidence below 0.80. Pair response validation binds both ordered document hashes and the observation ID and rejects inconsistent review state; it does not authenticate transport or verify signatures. Partial invoicing preserves resolved over-order discrepancies. Zero face value and small internal rounding differences require review without an automatic fraud accusation.

| Consumer input | Required interpretation |
|---|---|
| `/ocr/extract` shared fields | Existing request/response shape preserved. Incomplete required evidence returns 422. Respect injection flags, fraud score and confidence; never infer acceptance from HTTP success |
| `/ocr/verify` partial pair | Invoice and PO are separate uploaded sources. Check `status`, every unknown/mismatch check, review reasons and nullable `compatible_invoice`; missing capacity/acceptance evidence requires downstream assessment |
| `handoff` | Require a recognized schema/extraction/rule version and matching uploaded hashes. An unsigned response is evidence, not a signed instruction or transaction approval |
| `fraud_graph` | Follow versioned typed relationships and evidence locations. Node IDs are private correlation tokens; do not substitute bank tokens for verified wallet payees |
| Duplicate flags | Previously observed content only. An on-chain/global registry must separately establish whether financing already exists |
| Shared-account/cluster signals | Contextual review. Ownership, legitimate group treasury/factoring arrangements and collusion are not determined by OCR |

The actual pair [examples](ARCHITECTURE_CONSUMER_EXAMPLES.json) cover complete, missing-required, mismatched, international and experimental Chinese documents. The [both-engine smoke](ARCHITECTURE_MODEL_SMOKE.json) exercises local Paddle and Qwen through multipart HTTP. For PO injection, the outer handoff and the shared invoice projection both carry the need for review; consumers retaining only the projection still receive injection flags and confidence below 0.80.

The security owner should resolve authenticated transport or signed envelope design, principal/access scope, request-hash binding, freshness, replay controls, evidence access/retention and HMAC-key lifecycle. This module exposes no transaction/reset/history-download endpoints and has no signing key. Its public endpoints currently assume a trusted local MVP environment; network exposure needs that owner's controls.

The registry owner must resolve versioned migration before accepting international local-v2 keys. Existing shared v1 omits country/scheme and rounds to two decimal places; its limitations force review. The wallet owner must independently validate payee ownership/allowlists, invoice/decision binding, mandate caps, idempotency and registry/PO allocations. Bank tokens are not bank-ownership attestations. Policy rules and wallet guard decisions remain outside OCR's authority.

Adoption should first run the examples against each owner's contract tests, then inject PO-only instructions, unknown/null fields, changed hashes, duplicate submissions, altered payees and unknown schema versions into the integrated flow. No wallet execution, chain write, teammate notification or PM approval was performed by this packet.
