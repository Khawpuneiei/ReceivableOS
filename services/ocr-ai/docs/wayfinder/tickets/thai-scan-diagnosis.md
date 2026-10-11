---
name: Diagnose Thai scan recognition and field assignment
label: wayfinder:research
parent: ../map.md
status: resolved
assignee: codex-root
blocked_by: []
---

## Question

Are the missing Thai issue dates, buyer names and PO numbers caused by detection, recognition, row reconstruction or field assignment, and which smallest change addresses the measured cause?

## Investigation

- Reproduce the existing Thai invoice and PO scan failures. Inspect raw OCR text, bounding boxes and field-assignment decisions, with bank evidence redacted.
- Separate recognition errors from correct text assigned to the wrong party/field. Check Thai combining characters, label aliases, mixed Thai/English spans and date notation.
- Use a bounded experiment matrix for render resolution, rotation/orientation and crops. Change one factor at a time; retain the currently staged model as the baseline.
- Compare preprocessing or an alternative explicitly Thai-capable recognizer only after reading its official model support and runtime requirements. A newer default model is not evidence of better Thai recognition.
- Validate the recommendation on the independent corpus before closing the ticket. Initial diagnosis may use current fixtures.

## Evidence required to resolve

An error taxonomy, reproduced examples, before/after field and source-location results, timing/memory observations and a chosen minimal change. State remaining unknowns; report character accuracy only as a secondary diagnostic to critical-field accuracy.

## Primary reference

[PaddleOCR OCR pipeline documentation](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html): inspect supported recognition models and independently configurable preprocessing modules. Record the actual installed version, staged model identifiers and experiment configuration.

## Resolution

See the [six-workstream reliability review](../../RELIABILITY_REVIEW.md) and [baseline evidence](../../RELIABILITY_BASELINE.json). The experiment identifies a bounded next step without granting model outputs field-writing authority.
