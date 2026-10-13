"""Fictional Thai PromptPay / bill-payment QR codes stamped onto the showcase invoice."""

from __future__ import annotations

from io import BytesIO

import pymupdf
from datagen.showcase_invoices import SHOWCASE_PROFILES, build_pdf
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.pdfgen import canvas

from app.promptpay import BILL_PAYMENT_AID, PROMPTPAY_AID, crc16

SUPPLIER_TAX_ID = SHOWCASE_PROFILES[0]["supplier_id"]
OTHER_TAX_ID = "0105559123454"  # Fictional, valid Thai checksum, not the printed supplier.
TOTAL = SHOWCASE_PROFILES[0]["total"]


def _field(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def emv_payload(proxy_type: str, proxy: str, amount: str | None, *, corrupt_crc: bool = False) -> str:
    if proxy_type == "bill":
        account = _field("30", _field("00", BILL_PAYMENT_AID) + _field("01", proxy + "00"))
    else:
        sub = {"mobile": "01", "tax_id": "02", "ewallet": "03"}[proxy_type]
        account = _field("29", _field("00", PROMPTPAY_AID) + _field(sub, proxy))
    body = _field("00", "01") + _field("01", "12" if amount else "11") + account + _field("53", "764")
    if amount:
        body += _field("54", amount)
    body += _field("58", "TH") + "6304"
    crc = crc16(body)
    return body + ("0000" if corrupt_crc and crc != "0000" else crc)


def with_qr(content: bytes, payload: str) -> bytes:
    with pymupdf.open(stream=content, filetype="pdf") as doc:
        page = doc[0]
        memory = BytesIO()
        pdf = canvas.Canvas(memory, pagesize=(page.rect.width, page.rect.height), invariant=1)
        code = QrCodeWidget(payload)
        x0, y0, x1, y1 = code.getBounds()
        size = 80
        drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
        drawing.add(code)
        renderPDF.draw(drawing, pdf, 455, 142)
        pdf.save()
        with pymupdf.open(stream=memory.getvalue(), filetype="pdf") as qr:
            page.show_pdf_page(page.rect, qr, 0)
        return doc.tobytes(deflate=True, no_new_id=True)


CASES = {
    # name: (payload kwargs, expected codes)
    "matching_tax_id": ((("tax_id", SUPPLIER_TAX_ID, TOTAL), {}), set()),
    "matching_bill_payment": ((("bill", SUPPLIER_TAX_ID, TOTAL), {}), set()),
    "matching_static_no_amount": ((("tax_id", SUPPLIER_TAX_ID, None), {}), set()),
    "swapped_payee": ((("tax_id", OTHER_TAX_ID, TOTAL), {}), {"qr_payee_mismatch"}),
    "swapped_bill_payee": ((("bill", OTHER_TAX_ID, TOTAL), {}), {"qr_payee_mismatch"}),
    "wrong_amount": ((("tax_id", SUPPLIER_TAX_ID, "74900.00"), {}), {"qr_amount_mismatch"}),
    "mobile_payee": ((("mobile", "0066812345678", TOTAL), {}), {"qr_payee_unverified"}),
    "edited_crc": ((("tax_id", SUPPLIER_TAX_ID, TOTAL), {"corrupt_crc": True}), {"qr_crc_invalid"}),
}


def case_pdf(name: str, invoice_no: str) -> bytes:
    (args, kwargs), _ = CASES[name]
    clean = build_pdf({**SHOWCASE_PROFILES[0], "invoice_no": invoice_no})
    return with_qr(clean, emv_payload(*args, **kwargs))
