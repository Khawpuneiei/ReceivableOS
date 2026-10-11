# Synthetic Shopify Invoice Test Pack

Open, **fictional** supplier invoices for testing OCR, document AI, LLM/VLM extraction, product matching, tax/discount handling and Shopify supplier-invoice workflows.

This dataset exists so teams can share fixtures without publishing real supplier documents.

- **Version:** v1.0.0
- **Includes:** 15 fictional supplier invoice test scenarios with PDF, PNG and `expected.json` ground truth
- **License:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- **Companion guide:** [Testing Supplier-Invoice Automation for Shopify](https://www.salorworks.app/resources/shopify-supplier-invoice-testing-guide)
- **Dataset page:** [salorworks.app/resources/synthetic-shopify-invoice-test-pack](https://www.salorworks.app/resources/synthetic-shopify-invoice-test-pack)

## Quick start

1. Choose a fixture directory, such as `fixtures/01-simple-english/`.
2. Send `invoice.pdf` or `invoice.png` to the extractor you want to test.
3. Compare the extracted result with that fixture's `expected.json` ground truth.

## Why synthetic invoices

Real supplier invoices contain confidential commercial data. Synthetic fixtures can be version-controlled, cited in benchmarks and redistributed. Each fixture includes `expected.json` as ground truth so extractors can be compared on the same files.

## Layout

```text
schema/expected.schema.json
fixtures/
  01-simple-english/
    invoice.pdf
    invoice.png
    expected.json
    README.md
  ...
```

`expected.json` is canonical. The PDF and PNG are renderings of that ground truth. Arabic, bilingual and poor-scan PDFs are rasterized from the PNG so shaping and scan artefacts stay intact. Other PDFs are native text.

For multi-page fixture `02-multipage`, `invoice.pdf` contains every page. `invoice.png` is page 1.

## Fixtures

| ID | Scenario | What it tests |
|---|---|---|
| `01-simple-english` | Simple English invoice | Single-page AED table with a clean subtotal, tax and total |
| `02-multipage` | Multi-page English invoice | Line items across pages with repeated headers |
| `03-arabic` | Arabic invoice | Arabic supplier and product text with right-to-left layout |
| `04-bilingual` | Arabic / English bilingual invoice | Mixed directionality and bilingual product fields |
| `05-uae-vat` | UAE AED + VAT invoice | AED, TRN-style fields and a 5% VAT example |
| `06-saudi-sar` | Saudi SAR invoice | SAR, bilingual text and regional tax fields |
| `07-kuwait-kwd` | Kuwait KWD invoice | Three-decimal values with no assumed VAT line |
| `08-usd-for-aed` | USD supplier invoice for an AED merchant | Explicit foreign currency for FX-policy tests |
| `09-line-discount` | Line-level discount | An individual SKU discount with net line totals |
| `10-invoice-discount` | Invoice-level discount | An overall discount for allocation logic |
| `11-freight-duty` | Freight + duty | Separate freight and customs lines for landed-cost tests |
| `12-case-pack` | Case-pack invoice | 5 cases × 12 units = 60 Shopify eaches |
| `13-free-of-charge` | Free-of-charge / bonus quantity | Charged for 10, delivered 12 |
| `14-poor-scan` | Poor-quality scan / photo | Rotation and uneven contrast as an OCR challenge |
| `15-multicolumn` | Difficult multi-column layout | SKU, barcode, qty, discount, tax and total in one dense table |

Tax rates, TRNs and barcodes are invented examples for extraction tests. They are not tax advice and are not real registrations.

## How to use it

Point an extractor at `invoice.pdf` or `invoice.png`, then compare the result with `expected.json`.

That works for Azure Document Intelligence, Google Document AI, AWS Textract, OCR libraries, LLM/VLM extraction, or an internal Shopify invoice processor. This repository is **not** an official integration with those providers.

Suggested checks:

- header fields (supplier, invoice number, date, currency)
- line accuracy (description, SKU, barcode, qty, unit price, line total)
- financial reconciliation (quantity × unit price, discounts, tax, freight, duty, total)
- product identifiers for matching tests
- pack conversion and free-of-charge quantities where present

## Schema

Field names are defined in [`schema/expected.schema.json`](schema/expected.schema.json). Keep them stable. Optional line fields include `descriptionArabic`, `pack`, `deliveredQuantity` and `freeOfChargeQuantity`.

## Citation

If you use this dataset in research, benchmarks, evaluation or documentation, cite version v1.0.0. Machine-readable citation metadata is available in [`CITATION.cff`](CITATION.cff).

## Regenerating fixtures

```bash
npm install
npm run generate
```

Noto fonts are downloaded into `fonts/` (gitignored) at generate time.

## Contributing

Issues and pull requests are welcome, especially for:

- additional fictional edge cases
- clearer fixture artwork
- extraction failures against the current ground truth
- schema improvements that stay backward compatible

Keep every invoice fictional. Do not add real supplier documents, live TRNs, or confidential prices.

## Disclaimer

This dataset is for software testing. It is not accounting, tax or customs advice. Suppliers, addresses, tax registrations, barcodes and amounts are invented.

Salor Invoice was shaped by the same invoice-processing problems these fixtures encode. The pack itself is not a product advertisement.
