"""Edited-PDF forgeries of the fictional showcase invoice, plus benign edits.

Every forgery raises the invoice consistently (unit price, line total, subtotal,
VAT, total and header) so arithmetic checks still pass, and gives it a new
invoice number so duplicate checks do not fire. What is left is the edit trace.
"""

from __future__ import annotations

import os
import tempfile

import pymupdf
from datagen.showcase_invoices import SHOWCASE_PROFILES, build_pdf

FORGERY = {
    "Invoice No: TAMPER-BASE-0001": "Invoice No: {invoice_no}",
    "THB  749,000.00": "THB  856,000.00",
    "14.00": "16.00",
    "700,000.00": "800,000.00",
    "Subtotal: 700,000.00": "Subtotal: 800,000.00",
    "Tax: 49,000.00": "Tax: 56,000.00",
    "Total: 749,000.00": "Total: 856,000.00",
}
FONTS = {"Helvetica": "helv", "Helvetica-Bold": "hebo"}
ATTACKS = (
    "cover_retype",
    "cover_retype_incremental",
    "redact_retype",
    "redact_retype_incremental",
    "redact_retype_other_font",
)
BENIGN = ("clean", "resaved", "metadata_incremental", "annotated")


def base_invoice() -> bytes:
    return build_pdf({**SHOWCASE_PROFILES[0], "invoice_no": "TAMPER-BASE-0001"})


def _background(page: pymupdf.Page, rect: pymupdf.Rect) -> tuple[float, float, float]:
    pixmap = page.get_pixmap(clip=pymupdf.Rect(rect.x0 - 2, rect.y0, rect.x0 - 1, rect.y0 + 1), alpha=False)
    return tuple(channel / 255 for channel in pixmap.pixel(0, 0)[:3])


def _apply(doc: pymupdf.Document, method: str, invoice_no: str, other_font: bool) -> None:
    page = doc[0]
    targets = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if span["text"] in FORGERY:
                    targets.append(span)
    for span in targets:
        rect = pymupdf.Rect(span["bbox"])
        fill = _background(page, rect)
        if method == "cover":
            page.draw_rect(rect + (-0.5, -0.5, 0.5, 0.5), color=None, fill=fill)
        else:
            page.add_redact_annot(rect, fill=fill)
    if method == "redact":
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
    for span in targets:
        text = FORGERY[span["text"]].format(invoice_no=invoice_no)
        font = "tiro" if other_font and "Total" in text else FONTS.get(span["font"], "helv")
        color = pymupdf.sRGB_to_pdf(span["color"])
        page.insert_text(span["origin"], text, fontsize=span["size"], fontname=font, color=color)


def forge(kind: str, invoice_no: str) -> bytes:
    method = "cover" if kind.startswith("cover") else "redact"
    incremental = kind.endswith("incremental")
    other_font = kind.endswith("other_font")
    clean = base_invoice()
    if incremental:
        with tempfile.TemporaryDirectory(prefix="ocr-tamper-") as folder:
            path = os.path.join(folder, "edit.pdf")
            with open(path, "wb") as handle:
                handle.write(clean)
            with pymupdf.open(path) as doc:
                _apply(doc, method, invoice_no, other_font)
                doc.saveIncr()
            with open(path, "rb") as handle:
                return handle.read()
    with pymupdf.open(stream=clean, filetype="pdf") as doc:
        _apply(doc, method, invoice_no, other_font)
        return doc.tobytes(deflate=True, no_new_id=True)


def benign(kind: str, invoice_no: str) -> bytes:
    clean = build_pdf({**SHOWCASE_PROFILES[0], "invoice_no": invoice_no})
    if kind == "clean":
        return clean
    with tempfile.TemporaryDirectory(prefix="ocr-benign-") as folder:
        path = os.path.join(folder, "doc.pdf")
        with open(path, "wb") as handle:
            handle.write(clean)
        with pymupdf.open(path) as doc:
            if kind == "resaved":
                doc.set_metadata({**doc.metadata, "producer": "Example re-save"})
                return doc.tobytes(deflate=True, no_new_id=True)
            if kind == "annotated":
                doc[0].add_text_annot((550, 805), "Received by AP on 2026-10-02")
                return doc.tobytes(deflate=True, no_new_id=True)
            doc.set_metadata({**doc.metadata, "keywords": "approved-ap-batch-42"})
            doc.saveIncr()
        with open(path, "rb") as handle:
            return handle.read()
