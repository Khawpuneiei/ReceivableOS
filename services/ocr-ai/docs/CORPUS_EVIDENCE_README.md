# Optional OCR corpus and evidence

This companion branch `ocr/corpus-evidence` depends on core PR #16 (`ocr/evidence-fraud-graph`). It restores OCR-owned corpus inputs, source attribution, historical design/Wayfinder notes and disposable grounding experiments separately from the service implementation. It adds no shared API change or other-service implementation.

The core retains four demo PDFs, the PM legacy text fixture and the licensed Thai regression font. Additional renders here are fictional development data: 80 English/experimental Chinese/Thai reliability documents, 13 English financing-case documents, showcase previews/matching PO, and an attributed 15-scenario publisher invoice pack. The pack's `expected.json`, licenses, checksums and citation are source annotation/provenance, not generated evaluation outputs. Preserve them together.

No generated `services/ocr-ai/docs/*.json` evaluation report is committed. Historic Markdown report links refer to locally regenerated artifacts; historical results are not a claim about current runtime. Current run steps/validation live in the core README and REVIEW_FOLLOWUP.md. Scenarios inspected during development are not an independent holdout.

## Reproduce

Create a virtualenv with the core requirements first, then from the repository root:

```bash
services/ocr-ai/.venv/bin/python services/ocr-ai/datagen/showcase_invoices.py
services/ocr-ai/.venv/bin/python services/ocr-ai/datagen/financing_case.py
services/ocr-ai/.venv/bin/python services/ocr-ai/datagen/reliability.py
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/eval.py
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/evaluate_lines.py
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/evaluate_reliability.py
services/ocr-ai/.venv/bin/python services/ocr-ai/scripts/replay_grounding.py
services/ocr-ai/.venv/bin/python -m pytest services/ocr-ai -q -p no:cacheprovider
```

The external PNG/scan evaluation requires explicitly staged English Paddle models; use requirements-ocr.txt and scripts/stage_paddle.py first, then scripts/evaluate_external_invoices.py. Do not invoke live hosted inference just to reproduce offline metrics. Corpus generators produce deterministic synthetic artifacts; they do not download external documents or authenticate issuers.

Independent licensed vendor documents, adjudicated fraud/benign labels, separate holdout splits and live hosted inference remain future validation work. The publisher pack's historic header result was 77.59%, below the target. Chinese is experimental/review-only; Thai scans still have errors. Preserve these limits in presentations and consumer adoption decisions.
