# Synthetic invoice showcase

These are two fictional, one-page English invoices made to look like business documents rather than OCR stress labels. One uses a branded goods-supplier layout; the other uses a service-invoice layout with a visible payment-due panel. Both include vendor and buyer details, an invoice number, matching purchase-order reference, issue and due dates, itemized rows, tax, totals, terms, and a remittance-security note.

The entity names, example-domain email addresses, identifiers, addresses, phone numbers, invoice numbers, purchase-order numbers, services, goods, and amounts are invented. No customer invoice, bank receipt, bank account, or payment confirmation is included. The amounts are internally consistent. These are demonstration fixtures, not legal or tax advice and not valid tax documents.

The current integration deliberately returns `review` for both US examples because its legacy fingerprint contract is scoped to Thai `TAX_ID` parties. The OCR fields and all invoice-to-PO comparison checks match; the review is the existing global-identity compatibility guard, not a planted fraud finding or extraction mismatch.

## Why these are invoices

An invoice requests payment; a receipt records payment already received. These samples say **INVOICE**, show an amount due and due date, and contain payment terms. They do not show a transfer receipt or claim that payment has settled.

## Research references

- [Xero US invoice template](https://www.xero.com/us/templates/invoice-template/) describes an invoice label, invoice number, dates, line items, quantities, rates, tax, total, and payment instructions.
- [QuickBooks professional invoice template](https://quickbooks.intuit.com/r/invoicing/professional-invoice-template/) recommends clear business and customer details, dates, itemized goods or services, quantities and rates, the total due, and payment details.

Those pages informed the field checklist only. The layouts, brands, and invoice content here were authored for this repository; no source invoice was copied.

## Regenerate and test

From the repository root:

```bash
services/ocr-ai/.venv/bin/python services/ocr-ai/datagen/showcase_invoices.py
services/ocr-ai/.venv/bin/python -m pytest services/ocr-ai/tests/test_pipeline.py -k showcase -q
```

The two PDFs preserve explicit field labels and the service's supported six-column item table so the polished layout can be checked through the current extraction path.
