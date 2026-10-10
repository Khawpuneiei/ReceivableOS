# Independent OCR and fraud holdout: access and readiness

Reviewed: 11 October 2026. The current evaluation files remain synthetic/development data. This note records public research candidates, their actual fit, and the evidence still required before any global-accuracy or real-fraud claim.

## Dataset decision

| Source | What the source provides | Fit for ReceivableOS | Access/licence status and decision |
|---|---|---|---|
| [DocILE repository and benchmark](https://github.com/rossumai/docile), [paper](https://arxiv.org/abs/2302.05658) | Business documents with field locations and line-item grouping; official KILE/LIR evaluation and precomputed OCR. | Best candidate found for English business-document layout/line extraction. It is not a fraud-label corpus and its fields still need a reviewed mapping to our Invoice schema. | Official download instructions require a secret token from the DocILE site. The GitHub repository's MIT licence describes the repository/code; do not assume it grants rights to the separately gated documents. No token, data download, or dataset-specific permission review was available for this run. |
| [XFUND repository](https://github.com/doc-analysis/XFUND), [ACL Findings paper](https://aclanthology.org/2022.findings-acl.253/) | Human-annotated visually rich forms with key/value fields in seven languages, including Chinese. | Useful only as a Chinese form/KV layout stress test. Forms are not invoices and do not validate invoice amount/date/tax/line rules or fraud detection. | The project states CC BY-NC-SA 4.0. Keep it out of the distributed demo and main invoice score. A non-commercial research run would need attribution/share-alike handling and confirmation that the intended use is compatible. No files were downloaded. |
| [ICDAR-SROIE team repository](https://github.com/zzzDavid/ICDAR-2019-SROIE) | 1,000 scanned receipts; the repository describes 600 train/validation and 400 test images, text boxes/transcripts, and key fields such as company/date/total. | A supplemental receipt OCR smoke set only. Receipts are not B2B invoices/POs and provide no fraud-ground-truth, bank ownership or cross-document financing labels. | GitHub displays an MIT licence for the team repository; its data links lead to the separate ICDAR dataset. That does not establish the dataset's reuse/distribution terms. Do not copy it into this repo until the dataset-specific terms are verified. No files were downloaded. |
| Current Shopify fictional invoice pack | 15 fictional invoice scenarios with publisher `expected.json`, PDF and PNG examples, attribution and SHA-256 records. | Useful challenge/development set for amounts, currencies, discounts, freight, line tables and poor scans. | Already retained with CC BY 4.0 attribution. It was used to improve parsing, so it is development evidence, not an independent holdout. Current measured score is recorded in `EXTERNAL_INVOICE_EVALUATION.json`. |
| ReceivableOS generated English/Chinese/Thai corpora | Reproducible layouts, attacks, benign negatives, duplicate/graph sequences and case packs. | Essential regression and safety tests; useful for controlled failure diagnosis. | Synthetic, generated with labels. Keep as development/regression evidence only; same generator and labels cannot prove real-world generalization. |

The dataset review did not find a permissioned public corpus that pairs B2B invoices with independently adjudicated genuine-fraud labels, shared-bank ownership verification and confirmed financing outcomes. Generic transaction fraud data and document-forgery images are different targets; they cannot establish invoice-fraud precision/recall. Build that evaluation from partner-approved, privacy-reviewed invoice histories and documented adjudication, or continue to label results as synthetic scenario checks.

## Holdout protocol before claiming accuracy

1. Record source, dataset version, license/consent, SHA-256, source vendor/template family, language, page count, input type, annotation version and annotator review in a manifest. Keep documents outside Git unless redistribution is explicitly permitted.
2. Assign every invoice, PO, revision, duplicate, scan and sibling template from one source family to a single partition. Split by supplier/template family and, when dates exist, time; never random-split sibling pages or revisions.
3. Freeze field mapping, OCR/model versions, prompts, thresholds and normalization before opening the holdout. Use the holdout once for the report; any rule tuned after inspection becomes development data.
4. Report per language, input type and field: exact normalized match, field precision/recall, wrong-present rate, abstention rate, document-level completeness, evidence-location validity, line-item tuple precision/recall/F1 and review rate. Show confidence intervals and sample counts. Correct nulls are abstentions, not successful operational invoices.
5. Keep injection results separate: attack catch by mechanism, changed grounded values/attack success, benign hard-negative false-alert rate, and model-only alerts. Include benign QR, white-on-dark text, dense notes, revisions and recompressed scans.
6. Keep fraud evaluation separate from OCR: confirmed labels and adjudication reason; typology, time, supplier and buyer split; point-in-time features; precision/recall and precision-recall curve at a pre-registered threshold; false-positive workload; confidence intervals; and reviewer outcomes. Report synthetic planted signals only as rule-path regression.
7. Do not use a scanned receipt or Chinese form benchmark to fill missing B2B invoice/PO coverage. Publish each benchmark's domain and licence next to its metric.

## Evidence required to close the current gap

| Gap | Required evidence or dependency | Current state |
|---|---|---|
| English vendor/layout generalization | Permissioned source documents with independent labels and held-out supplier/template families | Not available here; the 15-document external pack is development data. |
| Chinese invoice performance | Native Chinese invoices/POs, currency/date/tax labels and human-checked field/line annotations | XFUND can only stress-test Chinese forms; invoice-specific evidence remains open. |
| Thai scan performance | Privacy-approved Thai scans across vendors/resolution/layouts, independent labels and reviewed normalization | Current generated scans show missing fields; no external Thai invoice holdout was available. |
| Injection false-positive/attack success | Paired benign and attacked invoices with controlled visual edits and source truth | Synthetic attack pairs pass current rule tests; no external invoice injection benchmark was identified. |
| Invoice-fraud precision/recall | Adjudicated fraud and benign near-miss histories, including group-payment and valid correction cases | Not available. Current 12 planted sequences are regression tests, not a real labelled set. |
| Bank-account ownership | A bank/open-banking/KYB provider, approved legal basis/consent, credentials, and independently verified test accounts | Not configured. OCR can tokenize observed account text and correlate repeats; it cannot verify ownership. |

Owner boundary: OCR keeps extraction, evidence, local graph signals and abstention. PM owns shared-contract review; Policy owns decision guards; Orchestrator owns evidence routing; Security/Wallet owners own authentication, payee verification and execution. See [Policy integration handoff](POLICY_INTEGRATION_HANDOFF.md) for the precise consumer checks.
