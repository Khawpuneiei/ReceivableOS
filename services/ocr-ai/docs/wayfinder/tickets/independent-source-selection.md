---
name: Select permitted independent English-first evaluation documents
label: wayfinder:research
parent: ../map.md
status: resolved
assignee: codex-root
blocked_by: []
---

## Question

Which independently sourced documents can be used for this project's evaluation under known access, privacy and reuse terms, with English prioritized and Chinese/Thai coverage stated honestly?

Evaluate source access and permitted use before obtaining data. DocILE is a research-access candidate, not an already downloaded or licensed corpus. Do not submit forms, contact people, accept terms or ingest private customer records under this research ticket.

Resolution requires a source/license manifest, field/line annotation rules with independent review where available, family-separated holdout design and a clear list of unavailable target-language cases. Generated truth and generator-based coordinates must remain separately reported.

## Resolution — 11 October 2026

Completed the source/access assessment and documented the manifest and frozen-split protocol in [DATASET_ACCESS_AND_HOLDOUT.md](../../DATASET_ACCESS_AND_HOLDOUT.md):

- DocILE is the strongest English business-document candidate, but its official download requires a secret access token; dataset-specific reuse terms remain to be reviewed. No token was available and no data were downloaded.
- XFUND includes human-labeled Chinese forms and states CC BY-NC-SA 4.0. It is not an invoice dataset and cannot establish invoice extraction accuracy. No data were downloaded.
- SROIE provides scanned receipt examples and labels; the MIT notice on the team repository does not establish separate reuse rights for the linked dataset. It is not B2B invoice or fraud evidence. No data were downloaded.
- No permissioned native Chinese/Thai invoice holdout or adjudicated B2B invoice-fraud dataset was available in the reviewed sources.

Research selection is resolved. Acquiring permissioned data, independently annotating it and running the frozen holdout remain a separate open task, contingent on access and consent.
