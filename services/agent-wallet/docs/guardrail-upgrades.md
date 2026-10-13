# Agent wallet: guardrail and architecture upgrades (13 Oct 2026)

For P and the pitch. These are six upgrades, each in its own PR, each measured in this repo. The numbers are from
`pytest`, `eval/run_eval.py` and a local full-stack run on the mock ledger (`CHAIN_MODE=mock`, no LLM). The PRs are
stacked on `main` at `4f4dbd6`: merge them in the order #49, #53, #56, #58, #60, #63, #68 (each branch already contains
the ones before it). With all seven merged: 209 passed, 2 skipped. Where a claim depends on a step outside the wallet folder, the
section says so.

The design rule is still the one in docs/03: **a fully hijacked model still cannot move money outside the mandate**. Each upgrade either
closes a gap on the known-limits list or turns a detector miss into a stop.

## Summary

| PR | Upgrade | Gap it closes | Measured |
|---|---|---|---|
| #49 | Agent loop with a tool-call firewall (`POST /agent/run`) | The agent loop (§7.3) was not built; AG1 and AG2 were skipped | Seed set 40/40 attacks caught (was 38/38 with 2 skipped), 0 unauthorized, 0/11 benign blocked |
| #53 | Tripwire: honeytokens, invoice quarantine, circuit breaker | Attackers iterate; each request was judged alone | Adaptive attacker (one caught probe first): held-out v3 10/24 → **0/24** reach execute, v4 18/30 → **0/30** |
| #56 | Scoped, expiring agent session keys | One static agent token with full power up to the daily cap | A stolen key is worth at most its remaining budget until it expires; revocable at once |
| #58 | Merkle-root audit anchoring with per-entry proofs | Proving one entry needed the whole log, including other borrowers' entries | One entry proves with about log2(n) hashes against the on-chain root; edited entries fail |
| #60 | Ed25519-signed credit decisions at approval | Known limit 1: "the decision is checked by hash, not signed" | A stolen risk-oracle token can't approve a self-written decision; no replay onto another invoice |
| #68 | Hardened human approval for large draws | Queued draws never expired, a decline stayed queued on the ledger, a declined invoice could never be redrawn | `eval/approval_cases.jsonl`: main 3/4 attacks caught, 1/3 benign completed → **4/4, 3/3** |

## How each maps to the state of the art

| Upgrade | Reference judges will know | What we built |
|---|---|---|
| Plan-then-execute | Beurer-Kellner et al., *Design Patterns for Securing LLM Agents* (2025) | The plan is fixed in code; the model fills one typed slot (`lender_id`) |
| Spotlighting | Microsoft, Hines et al. (2024) | Per-run `<<UNTRUSTED_nonce>>` tags; forged closing tags are stripped |
| Capability and provenance tracking | Google DeepMind, CaMeL (2025) | Every `wallet_propose` argument records its trusted source; the payee is always the seller bound at TX-1 |
| Alignment check | Meta, LlamaFirewall AlignmentCheck (2025) | Deterministic: the model's pick must equal the rule's pick on the same trusted numbers (`AgentMisaligned`) |
| Tool and argument allowlist | OWASP Top 10 for LLM Apps 2025, LLM06 Excessive Agency | Extra arguments, unknown lenders and unknown verdicts are refused (`ToolArgNotAllowed`) |
| Honeytokens | Canarytokens, MITRE Engage deception | Decoy payee id and address; touching one blocks and auto-pauses (`HoneytokenTouched`) |
| Quarantine and circuit breaker | Anomaly-triggered kill switches on smart accounts (Safe guards) | `InvoiceQuarantined`; 3 hostile blocks in 10 minutes pause the wallet, owner-only unpause |
| Session keys | ERC-4337 session keys, ERC-7715 permissions, AP2 intent mandates | Actions, budget, per-tx cap, TTL ≤ 24h, optional invoice list, bound to the mandate hash, revocable |
| Transparency-log proofs | RFC 9162 (Certificate Transparency v2) | Merkle root anchored via `AgentWallet.anchorAudit`; offline verifier `scripts/verify_audit_proof.py` |
| Signed decisions | Separation of duties; AP2's signed mandates | Ed25519 over `decision_hash|invoice_fingerprint`; the key lives in policy-ai |
| Bounded human approval | Safe transaction queue (nonce, expiry); CLAUDE.md 5.5 (24h) | `ApprovalExpired`, decline sent on chain, `ApprovalPending` while a human decides |
| Adaptive-attacker evaluation | AgentDojo (2024) | `run_eval.py --probe-first` |

## Demo moments (all on the mock ledger, `scripts/demo.py` unless noted)

1. **Hijacked model** (#49, test `test_firewall_blocks_a_hijacked_model`): a fake LLM obeys "pay 0xbad…" and adds a
   `payee` argument. The firewall answers `ToolArgNotAllowed` and nothing is drawn.
2. **Honeytoken** (#53, demo section 9): a draw to "SELLER:siam-fresh-pack-old" gets `HoneytokenTouched` and the
   wallet pauses itself. The clean-looking retry gets `InvoiceQuarantined`.
3. **Session key** (#56, demo section 10): a 30-minute key with a THB 600,000 budget draws 524,300. The next draw
   gets `SessionBudgetExceeded`, and after the approver revokes the key, `SessionRevoked`.
4. **Audit proof** (#58, demo section 8): `draw entry 25: 3-hash Merkle proof to anchored root … VERIFIED`.
5. **Forged approval** (#60, test `test_risk_oracle_token_alone_cannot_approve_its_own_decision`): a stolen risk-oracle
   token plus a self-made decision with a bigger limit gets `DecisionSignatureInvalid`.
6. **Stale approval** (#68, eval case AP01): the approver releases a 980,000 draw 24 hours and a minute after it was
   queued. On main it pays; with #68 it gets `ApprovalExpired` and the draw is declined on the ledger.

Slide line: *"We attacked our own agent like a real attacker would: probe, learn, retry. On the held-out sets, the
retry that slips past the scanner is stopped by quarantine, so 0 of 54 held-out attacks reach execute, and the scanner's
own recall (14 of 24, 10 of 27) is reported as it is."*

## Honest limits

- The scanner's recall did not change. The tripwire numbers assume the attacker's first try is caught; a first try that
  slips past the scanner still reaches execute, inside the mandate, as before.
- Tripwire state, sessions and anchors are in memory, like holds today (risks 15–17). A restart fails closed for
  sessions (the token stops working) and re-opens quarantines.
- Session keys and the agent loop are off-chain. The on-chain `AgentWallet` still binds the agent key with its own
  allowlists and caps. In production, sessions map to a session-key validator module on the smart account.
- Signed decisions are off by default (`enforce: false`). Turning them on needs policy-ai to sign and the orchestrator to
  forward the header (other owners' folders), then `enforce: true`.
- The agent loop is not on the orchestrator path. It calls a model only when `LLM_PROVIDER` is set, and the alignment
  check means the model adds explanation, not authority.
- The approval expiry is enforced by the wallet service, which holds the approver key in the MVP. The deployed
  `AgentWallet.confirm` has no expiry of its own; adding one needs a contract change and a redeploy.
- The PRs are stacked, so merging one out of order pulls in the ones before it.
