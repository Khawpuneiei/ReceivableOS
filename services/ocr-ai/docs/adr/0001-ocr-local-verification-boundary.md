---
status: accepted
---

# Keep pair verification inside OCR until the shared contract is reviewed

The user's start prompt requires independent extraction of an uploaded invoice and uploaded PO, while the current shared contract accepts one invoice upload. Add an OCR-local `POST /ocr/verify` proposal using `invoice_file` and `po_file`, preserve `POST /ocr/extract` and `shared.schemas.ExtractedInvoice`, and leave shared schemas and other services unchanged. Synthetic PO records are fixtures or an explicitly labeled fallback; they do not replace extraction of an uploaded PO. Cross-service adoption requires a separate PM-reviewed contract change, trading immediate integration for compatibility and clear ownership.
