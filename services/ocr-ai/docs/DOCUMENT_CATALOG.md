# ReceivableOS OCR evidence document catalog

This catalog maps the ReceivableOS receivable-financing journey to documents that may support a case. It separates documents the OCR service can currently process from documents that need a future type-specific extractor or a trusted external verification source. It is a product and test-design inventory, not a claim that every document is legally required in every market.

## Current labelled-template case support (10 October 2026)

`POST /ocr/cases/verify` now reads ten explicitly labelled English digital-PDF templates: delivery note, goods receipt, buyer confirmation, credit note, remittance advice, assignment notice, company registration, masked bank confirmation, beneficial-ownership declaration reference and insurance certificate. The [12-document synthetic case manifest](../../../data/invoices/financing_case/manifest.json), [field/support matrix](CHECKLIST_AND_DEMO.md) and [case loop results](CASE_LOOP_RESULTS.json) describe their narrow extraction and relationship checks. Every case retains issuer authenticity unknown and mandatory review; declared balances are not a settlement ledger.

“Future OCR” in the broader catalog below means arbitrary real-world layouts or the fuller semantic document models described in that row. It does not erase the named limited templates above. Bank statements, tax certificates, identity/signatory documents, contracts, transport documents, native XML/signatures and ownership percentages remain unimplemented.

## Support labels

| Label | Meaning |
| --- | --- |
| **Current OCR** | The current OCR API accepts this type and has implemented extraction/comparison rules. |
| **Current context only** | A related value exists as a demo profile field; no source document is authenticated or parsed. |
| **Future OCR** | Useful evidence for the product, but there is no typed extractor or OCR API contract for it yet. |
| **Prefer verified source** | OCR may help route or prefill the evidence; a registry, bank, buyer, carrier, signature verifier, or other trusted source should establish the authoritative fact. |

## Transaction and fulfillment evidence

| Document | What it can help check | Current OCR support | Suggested use and limits |
| --- | --- | --- | --- |
| Commercial invoice | Seller, buyer, invoice number/date, currency, tax basis, lines, amount, payment details | **Current OCR** | Extract with source evidence, validate arithmetic, bind to document hash, then compare to PO. An invoice is a payment claim; it does not prove delivery, acceptance, authenticity, or financeability. |
| Tax invoice / e-Tax invoice | Tax invoice identifiers, parties, tax and total | **Current OCR** for supported English/Thai/experimental Chinese layouts; no tax-compliance certification | Keep jurisdiction and invoice subtype explicit. Thai e-Tax exchange can involve XML and digital signatures; OCR of a rendered PDF does not verify either. |
| Purchase order / buyer order | Buyer authorization context, supplier, lines, quantity, price, currency and reference | **Current OCR** | Pair with the invoice and compare only fields grounded in both documents. A buyer's PO system or verified message is stronger evidence of authorization than a PDF alone. |
| Order acknowledgement / order response | Seller acceptance, promised quantity, terms, or changes to the PO | **Future OCR** | Model as a versioned event linked to a specific PO and line. Do not overwrite the original order. |
| PO change, cancellation, or replacement | Whether the authorized amount/quantity changed or the order was withdrawn | **Future OCR** | Preserve a chain of prior versions and cancellation state; identify the issuer and source channel. |
| Contract, framework agreement, statement of work | Recourse, payment terms, assignment restrictions, service scope, milestones | **Future OCR**; legal interpretation belongs outside OCR | Extract clause locations for review; do not let text extraction decide enforceability or legal rights. |
| Despatch advice / shipment notice / delivery note | What the seller says it shipped, when, and against which order lines | **Future OCR** | Match order line, shipment, quantity, date, carrier and referenced invoice; seller-issued evidence is not independent receipt proof. |
| Proof of delivery / carrier waybill / bill of lading / air waybill | Carrier, shipment, consignee, route and delivery event references | **Future OCR**; **Prefer verified source** for event status | Verify tracking, carrier, signature and status through the carrier or signed channel when available. International shipments add transport and country-risk context. |
| Packing list / customs declaration / certificate of origin | Package contents, export/import declaration, origin and cross-border references | **Future OCR** | Use for cross-document consistency and exception review. Do not infer delivery or ownership from an extracted declaration. |
| Receipt advice / goods-received note | Buyer's record of quantities received, shortages, damage or rejection | **Future OCR** | Compare received quantities with PO and dispatch evidence. OASIS UBL describes Receipt Advice as buyer/delivery-party evidence of receipt and possible shortages or damaged items. |
| Service completion, milestone acceptance, timesheet, usage report | Whether a non-goods service or milestone was recorded as completed | **Future OCR** | Link to a contract/SOW, service period, approver and invoice lines; require an authorized buyer acknowledgement where product policy needs it. |
| Buyer confirmation / acceptance | Buyer's acknowledgement of the payable, invoice or delivery | **Current context only** as `buyer_confirmed` in a demo profile | The boolean is synthetic profile data, not evidence. A future flow should capture source, authenticated party, timestamp, scope, amount, dispute status and revocation. |

UBL defines common business document types and their references across order, invoice, despatch, receipt, credit/debit note and transport flows. Peppol Billing likewise has invoice and credit-note syntax and supports references to order, receipt, despatch and supporting documents. These are useful interoperability sources, not a universal mandatory checklist: [OASIS UBL 2.3](https://docs.oasis-open.org/ubl/UBL-2.3.html), [Peppol BIS Billing 3.0](https://docs.peppol.eu/poacc/billing/3.0/).

## Adjustments, payment and receivable status

| Document | What it can help check | Current OCR support | Suggested use and limits |
| --- | --- | --- | --- |
| Credit note | Reduction, return, discount, tax adjustment or correction against an earlier invoice | **Future OCR** | Link to the original invoice and affected lines; recalculate net eligible receivable and prevent financing the unreduced gross amount. |
| Debit note | Additional charge or adjustment | **Future OCR** | Link to the original invoice/contract and require explicit reason and counterparty evidence. |
| Return, damage, rejection or dispute record | Dilution, disputed goods/services or withheld payment | **Future OCR** | Treat as a lifecycle event that can lower or suspend eligibility; preserve resolution evidence. |
| Replacement/corrected invoice and cancellation notice | Which invoice supersedes which and whether the earlier claim is void | **Future OCR** | Build a supersession graph and keep the prior hash/status; do not treat replacement as a second payable. |
| Remittance advice / payment receipt | Payer's allocation of a payment to invoices | **Future OCR** | Reconcile partial payment, deductions and allocation; verify against bank or buyer records. |
| Bank statement / transaction confirmation | Cash movement and payment/beneficiary details | **Future OCR**; **Prefer verified source** | Use bank feeds or signed bank evidence where possible. OCR is not proof that funds settled or that the account belongs to the supplier. |
| Accounts-receivable aging / sales ledger | Outstanding balance, aging, previous payments and dilution | **Future OCR** | Reconcile rows against invoices, credit notes and settlements; detect inconsistent totals and repeated receivables. |

## Entity, authority and financing evidence

| Document or record | What it can help check | Current OCR support | Suggested use and limits |
| --- | --- | --- | --- |
| Company registration / business license | Legal name, registration number, status and jurisdiction | **Future OCR**; **Prefer verified registry** | OCR can compare identifiers and names; a company registry is the source of current legal status. |
| Tax/VAT registration certificate | Tax ID, scheme, jurisdiction and registration details | **Future OCR**; **Prefer verified tax registry** | Apply country-specific rules only after jurisdiction and scheme are established. |
| Ownership chart / beneficial-owner declaration | Ownership and control relationships | **Future OCR**; **Prefer verified registry and review** | Capture provenance, effective date, ownership percentages and natural-person control. Requirements vary by jurisdiction and risk. FATF guidance describes a multi-source approach to beneficial ownership information. |
| Director, signatory, identity and board-authority evidence | Whether a person may act for the entity | **Future OCR**; **Prefer identity/authority verification** | Extract names and dates for matching; do not conclude identity, authorization or liveness from OCR. |
| Bank account certificate / void cheque / beneficiary-change instruction | Claimed payee account and changes to payment instructions | **Future OCR**; **Prefer bank/independent callback verification** | Keep raw account data private and tokenized for graph matching. Step-up verification is needed for beneficiary changes. OCR must not set the wallet payee by itself. |
| Receivable assignment / transfer notice / buyer acknowledgement | Claimed transfer of rights and whether the buyer received or acknowledged notice | **Future OCR**; legal review and verified counterparty status required | Link the assigned invoice set, parties, effective date, governing terms and acknowledgment. OCR cannot establish perfection or enforceability. |
| Registry / lien / prior-financing search result | Possible prior assignment or competing interest | **Future OCR**; **Prefer authoritative registry** | Record source, search time, jurisdiction, searched identifiers and result freshness. The OCR service does not own the financing registry. |
| Financing application, facility agreement and wallet mandate | Requested amount, facility constraints, authorized instructions and approvers | **Future OCR** or structured intake; Policy/Wallet-owned decisions | Parse relevant references only after the owning service defines a versioned contract. Never infer payment authority from invoice content. |
| Audited financial statements, management accounts, buyer credit report, credit insurance | Supplier/buyer repayment capacity, coverage and exclusions | **Future OCR**; Policy-owned interpretation | OCR can extract tables and dates for review; underwriting, coverage validity and risk decisions belong to Policy and verified providers. |

The OCC trade-finance handbook describes purchase-order finance and accounts-receivable/invoice finance as different risk stages and discusses importer, exporter, delivery-conformity, legal, FX and dilution risks. It is a US supervisory reference, not a global rulebook: [OCC Comptroller's Handbook: Trade Finance and Services](https://www.occ.gov/publications-and-resources/publications/comptrollers-handbook/files/trade-finance-services/pub-ch-trade-finance.pdf). FATF beneficial-ownership guidance is similarly a risk-based reference, with local law and registry practice determining the operational requirements: [FATF Guidance on Beneficial Ownership of Legal Persons](https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Guidance-Beneficial-Ownership-Legal-Persons.html).

For Thailand, the Revenue Department describes tax-invoice fields and invoice/credit-note/debit-note provisions, while ETDA describes e-Tax Invoice and e-Receipt formats and digital-signature/XML exchange. These rules should be applied only to the relevant Thai document and process: [Thai Revenue Department VAT invoice provisions](https://www.rd.go.th/english/37741.html), [ETDA e-Tax Invoice standard](https://www.etda.or.th/th/Our-Service/Standard/OID/Information/Our-Works/e-Tax-Invoice/e-Tax-Invoice.aspx), [ETDA e-Tax Invoice and e-Receipt FAQ](https://www.etda.or.th/en/contact/faq/e-Tax-Invoice-e-Receipt.aspx).

## Public sample and reference materials

| Resource | Document/examples available | Best use here | Caveat |
| --- | --- | --- | --- |
| [OASIS UBL 2.3 XML instances](https://docs.oasis-open.org/ubl/cs02-UBL-2.3/xml/) | Structured Invoice, CreditNote, DebitNote, DespatchAdvice, ReceiptAdvice and related examples | Build parsers and cross-document reference tests for native UBL XML; compare semantic field names and relationships | These are structured XML samples, not a representative scan/OCR layout set or real trade transactions |
| [Peppol BIS Billing 3.0 guide and example files](https://docs.peppol.eu/poacc/billing/3.0/bis/) | Invoice and Credit Note examples, including references and supporting-document patterns | Validate future e-invoice fields and invoice/credit-note linkage | Peppol rules are profile-specific; a document outside that profile must not be marked invalid merely for not using it |
| [ETDA Trade Services Message Standard](https://www.etda.or.th/getattachment/Our-Service/Standard/e-tax-Invoice-Receipt/Content/law/20170120-ER-EINVOICEV2-V08-16F-0711.pdf.aspx?lang=th-TH) | Thai XML message and digital-signature examples for e-invoice/e-tax exchange | Design a separate Thai native-XML/signature-validation path | Do not treat OCR of a PDF rendering as XML or signature validation |
| [ReceivableOS fictional Shopify invoice challenge pack](../../../data/invoices/external/shopify_invoice_test_pack/) | 15 fictional invoice PDFs plus raster examples and expected labels, including multipage, international VAT/currency, discount/freight and dense Arabic/English layouts | Supplemental invoice layout challenge for the current parser | Synthetic, invoice-only, and not a balanced or independent holdout; source/license/attribution files are retained locally |
| [DocILE benchmark](https://github.com/rossumai/docile) and [paper](https://arxiv.org/abs/2302.05658) | Business documents for field localization/extraction and line-item recognition; dataset access requires following publisher terms | Research field/line-item metrics and layout variation for future OCR evaluation | It is not a fraud dataset, does not cover the whole evidence lifecycle, and is not a substitute for permissioned local-language holdout data |

These sources provide examples or schemas, not proof that a supplier, buyer, shipment, account, signature or receivable is genuine. Before copying any external files into the repository, review license/access terms, preserve attribution and checksums, label synthetic data accurately, and keep development examples separate from holdout evaluation data.

## Recommended evidence-bundle architecture

The OCR boundary should evolve from the current `ExtractedInvoice` projection into typed document records only through a reviewed shared-contract change. Each record should carry:

- `document_type`, schema/extractor version, language and jurisdiction when observed;
- source hash, page-level evidence references and field status (`present`, `missing`, `ambiguous`, `conflicting`, or `unsupported`);
- issuer/recipient roles, document number/date, currency/tax basis, line references and explicit references to related records;
- provenance and verification status kept separate from extracted text (for example, `ocr_observed`, `signature_verified`, `registry_checked`, `buyer_confirmed`);
- lifecycle state and supersession links for corrections, cancellations, payments and disputes.

Use a case bundle with separate typed extractors and comparison rules. Keep `unknown` when either side lacks grounded evidence. A graph can link invoice, order, dispatch, receipt, adjustments, payer and beneficiary tokens; every suspicious relation needs evidence references. The current graph supports invoice duplicate candidates, shared bank-account tokens and suspicious clusters as OCR-local signals. Its noisy-OR score is uncalibrated, and the current shared handoff is unsigned. Policy must independently authenticate and enforce the handoff before it affects a decision.

Do not serialize raw bank values, graph node IDs, HMAC tokens or full OCR evidence into a public demo report. Keep the integration contract owner in control of how Policy receives a verified invoice-plus-evidence bundle; the current shared Policy request accepts only `ExtractedInvoice`, so pair checks and OCR graph handoff are not yet wired into that contract.

## Testing and research plan

1. Keep Invoice and PO as the current end-to-end baseline; add per-document synthetic fixtures for receipt, dispatch, credit/debit notes, payment, entity identity, assignment and transport records before claiming support.
2. For each type, label document class, required fields, source spans, related-document links and expected unresolved cases. Split holdouts by template/vendor family and language, not random page, to limit leakage.
3. Measure field exact match, evidence-grounding rate, pair-link precision/recall, unknown-vs-mismatch handling, duplicate/cluster signals, injection false positives, and Policy guard outcomes separately.
4. Include English as the primary global profile plus Thai and Simplified Chinese; treat Arabic and other scripts as unsupported until a named OCR profile and held-out corpus pass.
5. Evaluate XML/native structured e-invoices separately from raster OCR. Digital signatures, registry checks, bank verification and carrier events need independent validators; OCR accuracy is not a substitute.
6. Use public extraction benchmarks as layout research, not fraud ground truth. [DocILE](https://github.com/rossumai/docile) and its [benchmark paper](https://arxiv.org/abs/2302.05658) cover business-document field localization/extraction and line-item recognition; they do not establish ReceivableOS fraud precision or financing eligibility.

The automated local loop is documented in the [OCR service README](../README.md) and writes a sanitized [DEMO_LOOP_RESULTS.json](DEMO_LOOP_RESULTS.json). The loop uses synthetic examples and records current Policy stub failures instead of treating a successful HTTP response as a security pass.
