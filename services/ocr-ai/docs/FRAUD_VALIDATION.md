# OCR and fraud validation

Date: 2026-10-10
Branch: `ocr/evidence-fraud-graph`
Data: generated fictional documents and the checked-in, attributed development corpora

## Results

- `services/ocr-ai/.venv/bin/python -m pytest services/ocr-ai -q`: **149 passed**, with five PyMuPDF/SWIG deprecation warnings. This includes multipart API integration, graph, privacy, financial comparison, history, and OCR regressions.
- `services/ocr-ai/scripts/eval.py`: the generated English and Thai text-document set matched **91/91 annotated header fields** for each language; each language also matched **7/7** fields on its PO. The 10 planted fraud sequences (five per language) all emitted the expected signals.
- Injection checks in the same evaluation alerted on **4/4** injected documents, preserved all grounded fields in **4/4**, and alerted on **0/6** clean or benign-note documents.
- Local PaddleOCR `en_PP-OCRv5_mobile_rec` read the new 150-DPI invoice preview. Invoice number, amount, currency, issue date, due date, supplier, buyer, and one line item were present. Posting that scan and its PDF PO to `/ocr/verify` returned HTTP 200 / `matched`, with no mismatch or review reason and no raw example account in the response.
- `scripts/consumer_review.py` exercised actual multipart API examples after cleanup: clean pair `matched`, missing required fields `review`, invoice/PO discrepancy `mismatch`, international-scope English `review`, and experimental Chinese `review`.
- The mock transport smoke still used `data/invoices/demo/01_happy.pdf`: the clean path returned `pending_approval` and the repeat submission was blocked as a duplicate. Policy and wallet remain stubs; this does not validate downstream fraud policy, signatures, or transactions.

All counts above are scenario-level synthetic checks, not independent-vendor accuracy or fraud precision/recall.

## Fraud scenario coverage

| Scenario | Observed behavior | Main regression evidence |
|---|---|---|
| First clean invoice | No fraud finding; grounded invoice and PO compare as matched | `test_source_derived_invoice_and_po_fields_match`; `test_actual_pdf_extract_and_shared_compatibility` |
| Same bytes submitted again | `duplicate_invoice_hash` and `duplicate_fingerprint`; same-key retry is idempotent, changed bytes with that key conflict | `test_duplicate_bytes_semantics_retry_and_persistence` |
| Re-rendered semantic duplicate | Fingerprint duplicate without byte-hash duplicate | `test_duplicate_bytes_semantics_retry_and_persistence` |
| Same parties, reference, currency and date with a changed amount | `near_duplicate`, requires review; the internally consistent revision does not get a false `math_inconsistent` finding | `test_same_reference_amount_revision_is_a_near_duplicate_review` |
| Same supplier changes its bank account | `bank_account_changed`, review required, two-observation graph path and evidence; neither account value is returned | `test_same_supplier_bank_token_change_requires_review_without_leaking_account`; `test_source_derived_invoice_payee_change_is_reviewed_and_redacted` |
| Distinct suppliers show the same scoped account | `shared_bank_token`, score 0.15, review required, and an evidence-backed graph path; this is contextual review, not a fraud verdict | `test_graph_explanations_from_actual_uploads`; `test_source_derived_invoice_shared_bank_is_contextual_graph_signal` |
| Shared-account component has independent anomalies across distinct suppliers | `suspicious_cluster` appears only when at least two anomaly families and two scoped suppliers are represented | `test_shared_account_and_cluster_independent_evidence`; `test_correlated_amount_codes_do_not_satisfy_cluster_independence`; `test_graph_explanations_from_actual_uploads` |
| Invoice/PO total or currency disagrees; critical fields are absent | A grounded discrepancy stays `mismatch` with a named finding; missing evidence stays `unknown`/`review` rather than being filled in | `test_pair_mismatch_and_unknown`; `test_partial_quantity_cannot_hide_a_payable_above_the_full_order`; `test_printed_po_amount_difference_is_not_silently_matched` |
| Same account digits under another bank/country/scheme, names alone, or insufficient bank scope | No account merge is inferred from unscoped digits or names | `test_legal_and_bank_scopes`; `test_names_alone_and_same_entity_do_not_trigger_shared_accounts`; `test_line_unknown_is_review_and_bank_scope_is_not_inferred` |
| Evidence and storage privacy | Responses and stored observations omit the raw account; evidence references resolve to current and prior source documents | `test_account_cannot_leak_through_other_fields`; `test_fraud_evidence_locations_resolve_both_current_and_prior_sources`; `test_duplicate_bytes_semantics_retry_and_persistence` |

## What this implementation means

Fraud detection here is a deterministic rules-and-observation-graph feature, not a trained fraud classifier. It finds document-level signals such as duplicates, inconsistent totals, PO discrepancies, payee changes, shared-account relationships, and narrowly defined anomaly clusters. The score combines rule weights; it is **not a calibrated probability**. A shared account alone is a low-weight review signal and may have a legitimate explanation.

The observation store is bounded and local to this service. Account values are represented in the graph by scoped HMAC tokens; printed bank details are not bank-ownership verification. The graph does not establish that an invoice is authentic, that goods were delivered, that an account belongs to the supplier, or that an invoice has not been financed elsewhere. The service has no trusted allocation ledger, issuer signature, or confirmed-fraud labels.

The 80-document English/Chinese/Thai reliability corpus and the attributed 15-scenario external invoice pack remain development and regression inputs. The external pack exercises extraction/layout, not fraud labels. Neither corpus is a representative customer holdout. Promotion requires independently sourced and licensed documents, adjudicated benign and fraudulent outcomes, per-signal precision/recall and review-workload measurement, plus owner agreement on the downstream handoff.

## Reproduce

```bash
services/ocr-ai/.venv/bin/python -m pytest services/ocr-ai -q
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/eval.py
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/consumer_review.py
```

Evaluation and regression fixtures are generated into temporary locations. The active language/layout corpora and their attribution remain checked in separately.
