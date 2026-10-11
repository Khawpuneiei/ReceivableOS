# Source and use notes

This is a verbatim copy of the fixture assets and publisher metadata from
[SalorWorks/shopify-invoice-test-pack](https://github.com/SalorWorks/shopify-invoice-test-pack),
retrieved on 10 October 2026 from source commit
[`bb2e531cfa504e6f7200243620121c523f9f7622`](https://github.com/SalorWorks/shopify-invoice-test-pack/tree/bb2e531cfa504e6f7200243620121c523f9f7622).

The publisher identifies the pack as version 1.0.0 and licenses it under
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).
See the included `LICENSE`, `CITATION.cff`, and `README.md`. Attribution:
**Salorworks, Synthetic Shopify Invoice Test Pack, v1.0.0, CC BY 4.0.**

The publisher describes all suppliers, registrations, addresses, barcodes,
and amounts as fictional, and marks the documents as software-testing samples.
These are synthetic challenge fixtures, not genuine customer or vendor invoices,
not verified tax documents, and not accounting/tax advice. Preserve this notice
when sharing them. Do not replace these fixtures with confidential invoices.

Only fixture PDFs, PNGs, expected labels, fixture notes, the expected schema,
and source attribution were copied. The publisher's JavaScript generation
scripts and package files were not copied or executed. `SHA256SUMS` records the
copied source files.

The upstream README notes that `fixtures/02-multipage/invoice.png` is only page
1 while its `expected.json` labels the complete multi-page invoice. The local
evaluation therefore evaluates all 15 PDFs and the PNGs for the other 14
single-page fixtures; it does not score that page-1-only image against full
document ground truth.
