"""Reproducible fictional goods-receivable evidence pack; never bank-issued documents."""

import argparse
import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

SERVICE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SERVICE), str(SERVICE.parents[1])]
from datagen.showcase_invoices import SHOWCASE_PROFILES, build_pdf  # noqa: E402

from app.supporting import SUPPORT_FIELDS  # noqa: E402

VALUES = {
    "Shipped Quantity": "50000",
    "Received Quantity": "50000",
    "Unit": "EA",
    "Receipt Date": "2026-10-03",
    "Accepted Amount": "749000.00",
    "Confirmation Date": "2026-10-04",
    "Acceptance Status": "accepted",
    "Credit Amount": "10000.00",
    "Reason": "Illustrative packaging adjustment",
    "Remitted Amount": "50000.00",
    "Payment Reference": "FICTIONAL-PAY-001",
    "Assignee": "Example Receivables Fund Ltd.",
    "Notice Date": "2026-10-05",
    "Registered Name": "Siam Fresh Pack Co., Ltd.",
    "Registration Reference": "SYNTHETIC-REG-001",
    "Account Masked": "***3001",
    "Bank Institution": "EXAMPLE-TH-001",
    "Account Name": "Siam Fresh Pack Co., Ltd.",
    "Declaration Reference": "SYNTHETIC-UBO-001",
    "Policy Reference": "SYNTHETIC-INSURANCE-001",
    "Coverage Amount": "749000.00",
}


def supporting_pdf(kind: str, *, seed=20261001, overrides: dict | None = None) -> bytes:
    profile = SHOWCASE_PROFILES[0]
    fields = {
        "Document Type": kind,
        "Document No": f"SAMPLE-{seed}-{kind.upper()}",
        "Invoice Reference": profile["invoice_no"],
        "PO Reference": profile["po_no"],
        "Supplier Tax ID": profile["supplier_id"],
        "Buyer Tax ID": profile["buyer_id"],
        "Currency": profile["currency"],
        **{key: VALUES[key] for key in SUPPORT_FIELDS[kind]},
    }
    fields.update(overrides or {})
    for label in ("Registered Name", "Account Name"):
        if label in fields and label not in (overrides or {}):
            fields[label] = profile["supplier"]
    memory = BytesIO()
    pdf = canvas.Canvas(memory, pagesize=A4, invariant=1, pageCompression=1)
    width, height = A4
    pdf.setTitle(f"Fictional {kind.replace('_', ' ')} sample")
    pdf.setAuthor("ReceivableOS synthetic evidence generator")
    pdf.setFillColor(HexColor("#19384A"))
    pdf.rect(0, height - 135, width, 135, fill=1, stroke=0)
    pdf.setFillColor(HexColor("#FFFFFF"))
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(40, height - 64, kind.replace("_", " ").upper())
    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, height - 88, "RECEIVABLE CASE  |  SIAM FRESH PACK / MEKONG BASKET")
    pdf.setFillColor(HexColor("#087E82"))
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(40, height - 166, "FICTIONAL SAMPLE - NO SIGNATURE OR AUTHORITY VERIFIED")
    pdf.setFillColor(HexColor("#19384A"))
    pdf.setFont("Helvetica", 10)
    for index, (key, value) in enumerate(fields.items()):
        pdf.drawString(40, height - 212 - index * 29, f"{key}: {value}")
    pdf.setFillColor(HexColor("#59727A"))
    pdf.setFont("Helvetica", 9)
    pdf.drawString(40, 105, "Document claims require independent issuer / buyer / bank verification.")
    pdf.drawString(40, 89, "Amounts and identities are illustrative. This file does not authorize financing.")
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(40, 40, "SYNTHETIC EVIDENCE PACK  |  NOT A BANK OR CUSTOMER DOCUMENT  |  PAGE 1 OF 1")
    pdf.save()
    return memory.getvalue()


def generate(output: Path, *, seed=20261001) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for kind in ("invoice", "purchase_order", *SUPPORT_FIELDS):
        content = (
            build_pdf(SHOWCASE_PROFILES[0], kind=kind)
            if kind in {"invoice", "purchase_order"}
            else supporting_pdf(kind, seed=seed)
        )
        filename = f"{kind}.pdf"
        (output / filename).write_bytes(content)
        entries.append({"filename": filename, "document_type": kind})
    manifest = {"profile": "goods_receivable_demo", "documents": entries}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "provenance.json").write_text(
        json.dumps(
            {
                "seed": seed,
                "origin": "fictional-generated",
                "issuer_verified": False,
                "references": [
                    "https://docs.oasis-open.org/ubl/UBL-2.3.html",
                    "https://docs.peppol.eu/poacc/billing/3.0/",
                ],
                "sha256": {
                    entry["filename"]: hashlib.sha256((output / entry["filename"]).read_bytes()).hexdigest()
                    for entry in entries
                },
            },
            indent=2,
        )
        + "\n"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261001)
    args = parser.parse_args()
    print(json.dumps(generate(args.output, seed=args.seed), indent=2))
