# Policy and orchestration integration handoff

Status checked 11 October 2026 after merging main commit 7c7056c into ocr/evidence-fraud-graph. The current Policy implementation replaces the earlier fixed approval stub. The complete OCR release loop reports release_ready=true and zero Policy guard violations. The Policy suite passes 251 tests with 3 skipped; the OCR suite passes 184 tests locally and in a clean clone.

## Verified integration behavior

The release loop starts OCR, Policy, Wallet, and Orchestrator on temporary loopback ports with synthetic documents and mock chain mode. It uses ephemeral HMAC keys and temporary state; it removes generated documents after execution. The resulting sanitized report is DEMO_LOOP_RESULTS.json.

| Input | OCR result | Policy result observed | Evidence boundary |
|---|---|---|---|
| Clean synthetic invoice | Grounded fields and evidence references; no hard guard | approve; this demo does not independently validate credit-policy suitability | Synthetic happy path only |
| Visible injection | VISIBLE_INSTRUCTION; OCR requires review | review | Current integration guard verified |
| PO/amount mismatch with fraud score 0.70 | po_amount_mismatch and math_inconsistent; review required | reject | High-fraud-score guard verified; this does not prove typed PO evidence reaches Policy |
| Repeated invoice in the ordered demo | duplicate_fingerprint only after cosmetic PDF re-save; score 0.80 | Registry blocks the repeated flow before Policy | Registry path verified; the ordered OCR-only demo is not a Policy call |

The OCR-only ordered demo separately checks clean, injection, inflated-total (score 0.40), and duplicate evidence expectations. Policy's merged scenario fixtures and tests cover its own decision cases. Keep the distinction between an OCR evidence-gate check, an API-level Policy test, and an end-to-end Orchestrator run when presenting results.

## Remaining integration contract

The current shared Policy request carries one ExtractedInvoice plus supplier and buyer profiles. It does not carry the structured result from POST /ocr/verify, the supporting-case result, or the full finding-scoped fraud graph. The current demo therefore sends the compatible invoice projection and records the missing typed evidence handoff. A passing hard-guard loop is useful, but it does not prove Policy evaluated PO line comparisons, receipt quantities, acceptance evidence, or graph paths.

OCR rule codes are lower-case strings such as duplicate_invoice_hash, duplicate_fingerprint, and po_amount_mismatch. Policy fixtures use Policy-owned reason codes such as KO.DUPLICATE, KO.PO_MISMATCH, and HARD.FRAUD_SCORE. Do not rename OCR codes or assume string equality means semantic compatibility. The Policy adapter should retain the original OCR signals and add explicit, tested mappings.

A versioned optional evidence object is a proposal for PM review, not a current contract or signed attestation:

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

Evidence references must bind to the corresponding document hash, page, and bounding box. Keep raw document text, bank values, HMAC keys, graph node IDs, and unsigned claims out of the Policy payload. Unverified authenticity and an unsigned handoff must remain limitations, not successful verification.

## Next owner sequence

1. PM reviews the evidence fields, unknown/null handling, reason mapping, retention, authentication, and migration plan. If approved, make the shared schema change in a separate contract PR.
2. Policy owner keeps hard guards ahead of model scoring and tests each accepted evidence signal through PolicyRequest and PolicyDecision, including reason retention and malformed/null inputs.
3. Orchestrator owner forwards the approved versioned evidence object, keeps route errors distinct from decisions, and preserves the Registry duplicate block.
4. OCR owner reruns extract, invoice/PO verification, supporting-case verification, and the integrated demo against the accepted contract.
5. Wallet/security owner independently binds an approved Policy decision to invoice hashes, fingerprint, mandate, and payee. OCR's unsigned handoff does not authorize execution.

## Evaluation limits

The checks above use fictional generated documents and planted fraud sequences. They are regression evidence, not production precision/recall, global OCR accuracy, real fraud calibration, or proof of issuer, bank-account, signature, ownership, delivery, acceptance, or settlement authenticity. Live hosted inference and a permissioned independent holdout remain unverified. See DATASET_ACCESS_AND_HOLDOUT.md for source, access, and holdout requirements.
