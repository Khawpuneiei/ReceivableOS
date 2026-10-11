---
name: Define an independent invoice and PO evaluation corpus
label: wayfinder:research
parent: ../map.md
status: resolved
assignee: codex-root
blocked_by: []
---

## Question

Which document sources, annotation rules and split strategy can reveal extraction failures beyond the current generated template without leaking related documents into the holdout?

## Investigation

- Inventory current fixtures by language, type, layout and source. Start with a proposed 80-document design: 20 in each English/Thai invoice/PO cell, at least three layouts per cell. This is a starting budget, not sufficient proof of reliability.
- Include digital PDF, scans, rotated/blurred images, mixed scripts, missing fields, multiple pages and line tables. Keep difficult and ambiguous cases labeled rather than silently dropping them.
- Annotate header fields, monetary roles, currency/tax basis, line items, source page/location, and expected missing/ambiguous outcomes. Check whether two annotators agree on critical fields where independent review is available.
- Keep clean/injected/duplicate variants of a source document together. Split by source/layout/vendor family; freeze a holdout before prompt or parser tuning. Record synthetic versus independently sourced results separately.
- Evaluate candidate datasets for invoice/PO coverage, Thai support, licensing and privacy before selecting or downloading them. A public English invoice benchmark does not establish Thai support.

## Evidence required to resolve

A source manifest, proposed annotation schema, family split manifest and justified coverage matrix. Specify field accuracy, full-document match, line-item accuracy, wrong accepted critical fields, unresolved/review rate and latency. Leave unsupported deployment targets explicit rather than inventing them.

## Implementation handoff

Future assets belong under OCR-owned `data/invoices/**`; evaluation/annotation tools belong under `services/ocr-ai/**`. No customer-document collection is authorized by this planning ticket.

## Resolution

The user selected English primary with Chinese experimental and Thai secondary. The implemented 80-document synthetic stress design is described in [corpus specification](../../RELIABILITY_CORPUS.md). Independent real-source validation remains an explicit release limitation.
