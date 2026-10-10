# Policy and orchestrator integration handoff

Status: OCR-side evidence is ready for owner review; Policy and shared-contract changes are not included in the OCR branch. Checked against `ocr/evidence-fraud-graph` on 11 October 2026. The repository assigns credit decisions to Policy AI and the shared API/PR review to the PM. This packet makes the remaining integration work concrete without changing those owners' files.

## Confirmed gap

The shared contract in `shared/schemas.py` accepts an `ExtractedInvoice` with `confidence`, `injection_flags`, `fraud_score`, `fraud_flags`, `doc_hash`, and `invoice_fingerprint`. The root scope requires these pre-model controls:

1. Any non-empty `injection_flags` must produce `review`.
2. `fraud_score >= 0.30` must produce `reject`.
3. `confidence < 0.80` must produce `review`.

The checked-in `services/policy-ai/app/main.py` is still a fixed `approve` stub. The OCR integration loop sent a visible-injection invoice and a high-score amount mismatch (`fraud_score=0.70`) to that endpoint; it approved both, recording two control violations. The duplicate demo is stopped by Registry before Policy, so it is not evidence that Policy's duplicate branch works. See [the actual integration output](DEMO_LOOP_RESULTS.json) and [fresh release report](RELEASE_CHECK.json).

There is also a string-code compatibility decision to resolve before Policy consumes flags. The Policy build brief names `DUPLICATE_HASH`, `DUPLICATE_INVOICE`, and `PO_MISMATCH`; OCR currently emits lower-case rule codes such as `duplicate_invoice_hash`, `duplicate_fingerprint`, and `po_amount_mismatch`. Both sides type this as a string list, so schema validation alone will not reveal a semantic mismatch.

## Recommended guard order and code mapping

Run these deterministic checks before any credit model. A high fraud score must never be downgraded by a later review condition. When more than one rule fires, retain every reason in the response.

| Condition | Expected Policy result | OCR evidence / proposed code mapping |
|---|---|---|
| `fraud_score >= 0.30` | `reject` | Preserve the numeric score and all original OCR codes. `duplicate_invoice_hash` → `DUPLICATE_HASH`; `duplicate_fingerprint` → `DUPLICATE_INVOICE`; `po_amount_mismatch` → `PO_MISMATCH` only when an agreed pair/evidence bundle is available. |
| Otherwise, any injection flag | `review` | Preserve `VISIBLE_INSTRUCTION` or other exact OCR injection code. |
| Otherwise, `confidence < 0.80` | `review` | Preserve the measured confidence and OCR review reasons. |
| Otherwise, unsupported/unknown evidence or a non-blocking fraud signal | `review` | Never infer a missing PO allocation, issuer authenticity, bank ownership, delivery, acceptance, or settlement. |
| No hard guard and enough policy inputs | Evaluate the existing credit policy | `approve` is a credit-policy outcome, not an OCR outcome. |

The mapping above is a proposal for the Policy adapter; it does not rename OCR's checklist-required rule codes. The PM should approve any change to the shared contract in a separate `contract:` PR before consumers rely on new fields.

## Demo acceptance matrix for the owners

Use the same ordered generated files and call `/policy/decide` with the compatible `ExtractedInvoice` projection. Keep a separate Registry assertion for the duplicate because the orchestrated flow blocks that repeat before it reaches Policy.

| Input | OCR evidence result | Direct Policy expectation | What current integration proves |
|---|---|---|---|
| `01_happy.pdf` | no injection; low fraud score; grounded fields | `approve` only if the active credit rules also approve | Stub returns `approve`; this does not prove its credit rules. |
| `02_injected.pdf` | `VISIBLE_INSTRUCTION`; score below 0.30 | `review` | Actual Policy stub returns `approve` (violation). |
| `03_inflated.pdf` | `math_inconsistent`; score 0.40 | `reject` | Ordered OCR evidence gate rejects; add this exact file to the direct Policy regression after owner wiring. |
| `04_duplicate.pdf` | same raw hash and fingerprint as 01; score 0.96 after repeat | `reject` if called directly; Registry should block the integrated repeat first | Registry blocks the repeat. Policy duplicate handling is not tested by that path. |

Also keep the current independent PO mismatch integration case (`po_amount_mismatch`, `math_inconsistent`, score 0.70): direct Policy must reject, and the orchestration contract must preserve its comparison evidence rather than forwarding only a clean-looking invoice projection.

Minimum Policy-owner tests: guard outcomes above; rule execution before any model call; multiple reasons retained; exact code mapping; malformed/null fields do not approve; and every direct test passes through `PolicyRequest`/`PolicyDecision`. Minimum orchestrator tests: injection and pair evidence reach Policy; Registry duplicate remains blocked; route errors remain distinct from an approval. `scripts/release_check.py --strict` is the current combined gate and correctly remains red until the Policy stub is replaced.

## Versioned evidence-bundle proposal

The existing single-invoice `PolicyRequest` cannot carry the `/ocr/verify` comparison or the full `/ocr/cases/verify` result. If the PM wants Policy to make decisions using that evidence, add a separately reviewed optional field such as `ocr_evidence` in a new contract version. Keep the present invoice request working during migration.

```json
{
  "schema_version": "ocr-policy-evidence-v1",
  "invoice_doc_hash": "sha256:<raw invoice bytes>",
  "purchase_order_doc_hash": "sha256:<raw PO bytes or null>",
  "authenticity_status": "unverified",
  "signed": false,
  "comparison_version": "invoice-po-rules-v3",
  "pair_status": "review",
  "review_required": true,
  "review_reasons": ["VISIBLE_INSTRUCTION"],
  "checks": [
    {"field": "amount", "status": "match", "rule_code": "po_amount_match", "evidence_refs": ["inv:e1", "po:e1"]}
  ],
  "fraud": {
    "rules_version": "graph-rules-v2",
    "score_semantics": "uncalibrated_rule_aggregation",
    "score": 0.0,
    "flags": [],
    "findings": []
  }
}
```

The example is a shape proposal, not a current response or signed attestation. Real evidence references must bind to their own document hash/page/bbox; do not include raw document text, raw bank values, HMAC keys, graph node IDs, or unsigned claims as verified facts. Policy must treat `authenticity_status=unverified` and `signed=false` as limitations, not as successful authentication. Bank-token correlation must never populate Wallet payees.

## Required owner sequence

1. PM reviews the field names, null/unknown semantics, review precedence, retention, authentication, and migration plan; if accepted, open the required separate `contract:` PR.
2. Policy owner implements the deterministic guards and lower-case-to-Policy code adapter, then passes the direct endpoint tests.
3. Orchestrator owner forwards the reviewed evidence bundle and preserves the current Registry duplicate block.
4. OCR owner reruns `/ocr/extract`, `/ocr/verify`, `/ocr/cases/verify`, and the full integrated demo against the accepted consumer contract.
5. Wallet/security owners independently bind the final Policy decision to the invoice hashes, fingerprint, mandate and payee. OCR's unsigned handoff does not authorize execution.

No cross-service implementation or teammate message is implied by this packet. The OCR release gate remains `release_ready=false` until its owner controls pass.
