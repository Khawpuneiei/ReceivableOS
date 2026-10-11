# Source-derived invoice showcase

The polished Siam Fresh Pack sample reuses the fictional parties, tax identifiers, invoice and PO references, dates, line item, currency and amounts from the former flat OCR fixtures. It presents them in a one-page business invoice with a matching purchase order. The demo folder uses the same design for clean, visible-injection, inflated-total, exact-duplicate, and PO cases.

The old fixture printed `Tax Basis: inclusive` even though its values are `THB 700,000.00` subtotal + `THB 49,000.00` VAT = `THB 749,000.00` total. The polished sample corrects the basis to `exclusive` so the printed arithmetic is consistent. It labels the 7% VAT as illustrative; this is not tax guidance.

All identities, contact details, addresses and bank data are synthetic. The account number is a test value from the old synthetic fixture, shown only to exercise OCR's private account handling. The service must not return that raw value in its response. Each PDF is visibly marked as a fictional sample and is not a valid invoice, tax document, payment instruction, or proof of payment.

Invoices request payment; receipts record payment already received. These documents are invoices and a purchase order, not bank receipts or settlement confirmations.

## Design references

- [Xero invoice template](https://www.xero.com/us/templates/invoice-template/)
- [QuickBooks professional invoice template](https://quickbooks.intuit.com/r/invoicing/professional-invoice-template/)

The references informed the field checklist. No third-party invoice was copied.

## Regenerate and test

From the repository root:

```bash
services/ocr-ai/.venv/bin/python services/ocr-ai/datagen/showcase_invoices.py
services/ocr-ai/.venv/bin/python -m pytest services/ocr-ai/tests/test_pipeline.py -k 'source_derived or showcase' -q
```

The invoice and PO use explicit labels and the supported six-column line table, so the same source can be exercised through OCR extraction and invoice-to-PO verification. Fraud scenario PDFs are examples for testing review signals; none claims a confirmed fraud event.
