"""Generate polished, fictional invoice samples for visual and OCR review."""

from __future__ import annotations

import argparse
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

REPO = Path(__file__).resolve().parents[3]
OUTPUT = REPO / "data" / "invoices" / "showcase"
PAGE_W, PAGE_H = A4
MARGIN = 40

SHOWCASE_PROFILES = (
    {
        "style": "northstar",
        "brand": "NORTHSTAR",
        "brand_line": "PACKAGING SYSTEMS",
        "strapline": "SUSTAINABLE MATERIALS  |  BUSINESS SUPPLY",
        "supplier": "Northstar Packaging Systems, Inc.",
        "supplier_id": "SYN-US-NSTAR-1048",
        "supplier_country": "US",
        "supplier_scheme": "BUSINESS_ID",
        "supplier_address": "2490 Meridian Avenue  |  Seattle, WA 98101  |  US",
        "supplier_contact": "billing@northstar.example  |  +1 206 555 0148",
        "buyer": "Meridian Home Retail LLC",
        "buyer_id": "SYN-US-MHR-7712",
        "buyer_country": "US",
        "buyer_scheme": "BUSINESS_ID",
        "buyer_address": "980 Market Row  |  Portland, OR 97204  |  US",
        "buyer_contact": "ap@meridian-retail.example  |  +1 503 555 0182",
        "invoice_no": "NS-INV-2026-1048",
        "po_no": "NS-PO-88317",
        "issue_date": "2026-10-02",
        "due_date": "2026-11-01",
        "currency": "USD",
        "locale": "en-US",
        "language": "en",
        "tax_basis": "exclusive",
        "tax_label": "US sales tax  |  8.25%",
        "terms": "Net 30",
        "subtotal": "17250.00",
        "tax": "1423.13",
        "total": "18673.13",
        "lines": (
            ("NS-MAILER-01", "Recycled mailer - 12 x 16 in", "250", "EA", "32.00", "8000.00"),
            ("NS-CARTON-24", "Double-wall shipping carton", "500", "EA", "18.50", "9250.00"),
        ),
        "accent": "#13A89E",
        "dark": "#17344D",
        "pale": "#EDF5F7",
        "muted": "#587181",
    },
    {
        "style": "bluepeak",
        "brand": "BluePeak Cloud Advisory",
        "brand_line": "ENGINEERING SERVICES",
        "strapline": "CLOUD RESILIENCE  |  SECURITY  |  DELIVERY",
        "supplier": "BluePeak Cloud Advisory LLC",
        "supplier_id": "SYN-US-BLUEPEAK-2904",
        "supplier_country": "US",
        "supplier_scheme": "BUSINESS_ID",
        "supplier_address": "800 Beacon Street  |  Boston, MA 02108  |  US",
        "supplier_contact": "finance@bluepeak.example  |  +1 617 555 0129",
        "buyer": "Cobalt Ridge Commerce Inc.",
        "buyer_id": "SYN-US-COBALT-0506",
        "buyer_country": "US",
        "buyer_scheme": "BUSINESS_ID",
        "buyer_address": "71 Commerce Circle  |  Chicago, IL 60606  |  US",
        "buyer_contact": "accounts@cobaltridge.example  |  +1 312 555 0164",
        "invoice_no": "BCA-2026-0716",
        "po_no": "CR-PO-26106",
        "issue_date": "2026-09-18",
        "due_date": "2026-10-18",
        "currency": "USD",
        "locale": "en-US",
        "language": "en",
        "tax_basis": "exclusive",
        "tax_label": "Service tax  |  7.50%",
        "terms": "Net 30",
        "subtotal": "7910.00",
        "tax": "593.25",
        "total": "8503.25",
        "lines": (
            ("BCA-ARCH-36", "Cloud resilience architecture sprint", "36", "HRS", "185.00", "6660.00"),
            ("BCA-DR-01", "Production recovery simulation", "1", "DAY", "1250.00", "1250.00"),
        ),
        "accent": "#E46E52",
        "dark": "#263B57",
        "pale": "#F4F2EF",
        "muted": "#657383",
    },
)


def _color(value: str):
    return HexColor(value)


def _text(
    pdf: canvas.Canvas,
    x: float,
    top: float,
    value: str,
    *,
    size: float = 9,
    color: str = "#263B57",
    bold: bool = False,
) -> None:
    pdf.setFillColor(_color(color))
    pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    pdf.drawString(x, PAGE_H - top - size, value)


def _box(
    pdf: canvas.Canvas,
    x: float,
    top: float,
    width: float,
    height: float,
    fill: str,
    *,
    stroke: str | None = None,
    radius: float = 8,
) -> None:
    pdf.setFillColor(_color(fill))
    pdf.setStrokeColor(_color(stroke or fill))
    pdf.roundRect(
        x,
        PAGE_H - top - height,
        width,
        height,
        radius,
        fill=1,
        stroke=1 if stroke else 0,
    )


def _line(pdf: canvas.Canvas, x1: float, top: float, x2: float, color: str, width: float = 0.7):
    pdf.setStrokeColor(_color(color))
    pdf.setLineWidth(width)
    pdf.line(x1, PAGE_H - top, x2, PAGE_H - top)


def _field_row(
    pdf: canvas.Canvas,
    profile: dict,
    top: float,
    positions: tuple[float, ...],
    *,
    text_color: str | None = None,
    muted_color: str | None = None,
):
    primary = text_color or profile["dark"]
    secondary = muted_color or profile["muted"]
    values = (
        f"Issue Date: {profile['issue_date']}",
        f"Due Date: {profile['due_date']}",
        f"Currency: {profile['currency']}",
    )
    for x, value in zip(positions, values, strict=True):
        _text(pdf, x, top, value, size=8.1, color=primary, bold=True)
    _text(pdf, positions[0], top + 15, f"Locale: {profile['locale']}", size=7.5, color=secondary)
    _text(pdf, positions[1], top + 15, f"Language: {profile['language']}", size=7.5, color=secondary)
    _text(pdf, positions[2], top + 15, f"Tax Basis: {profile['tax_basis']}", size=7.5, color=secondary)


def _party_cards(pdf: canvas.Canvas, profile: dict, top: float, *, style: str):
    gap = 14
    width = (PAGE_W - (2 * MARGIN) - gap) / 2
    accent = profile["accent"]
    for index, party in enumerate(("supplier", "buyer")):
        x = MARGIN + index * (width + gap)
        _box(pdf, x, top, width, 126, "#FFFFFF", stroke="#DDE6EA", radius=8)
        _text(
            pdf,
            x + 12,
            top + 10,
            "SUPPLIER" if party == "supplier" else "BILL TO",
            size=7.2,
            color=accent,
            bold=True,
        )
        name = profile[party]
        _text(
            pdf,
            x + 12,
            top + 24,
            f"Supplier: {name}" if party == "supplier" else f"Buyer: {name}",
            size=8.1,
            color=profile["dark"],
            bold=True,
        )
        _text(pdf, x + 12, top + 39, profile[f"{party}_address"], size=7.1, color=profile["muted"])
        _text(pdf, x + 12, top + 52, profile[f"{party}_contact"], size=7.1, color=profile["muted"])
        _text(
            pdf,
            x + 12,
            top + 72,
            f"{party.title()} Tax ID: {profile[f'{party}_id']}",
            size=7.2,
            color=profile["dark"],
        )
        _text(
            pdf,
            x + 12,
            top + 87,
            f"{party.title()} Country: {profile[f'{party}_country']}",
            size=7.2,
            color=profile["dark"],
        )
        _text(
            pdf,
            x + 12,
            top + 102,
            f"{party.title()} ID Scheme: {profile[f'{party}_scheme']}",
            size=7.2,
            color=profile["dark"],
        )
    if style == "bluepeak":
        _line(pdf, MARGIN, top + 126, PAGE_W - MARGIN, "#E8E4DF", 1)


def _table(pdf: canvas.Canvas, profile: dict, top: float):
    table_width = PAGE_W - (2 * MARGIN)
    height = 28
    _box(pdf, MARGIN, top, table_width, height, profile["dark"], radius=5)
    columns = (
        (MARGIN + 9, "SKU"),
        (MARGIN + 82, "Description"),
        (MARGIN + 280, "Qty"),
        (MARGIN + 330, "Unit"),
        (MARGIN + 382, "Price"),
        (MARGIN + 464, "Total"),
    )
    for x, label in columns:
        _text(pdf, x, top + 9, label, size=7.3, color="#F6FAFB", bold=True)
    for index, cells in enumerate(profile["lines"]):
        row_top = top + height + 12 + index * 36
        if index % 2 == 0:
            _box(pdf, MARGIN, row_top - 5, table_width, 29, profile["pale"], radius=4)
        cell_positions = tuple(x for x, _ in columns)
        for x, value in zip(cell_positions, cells, strict=True):
            _text(pdf, x, row_top + 2, value, size=7.5, color=profile["dark"])
        _line(pdf, MARGIN, row_top + 30, PAGE_W - MARGIN, "#E2E8EB", 0.45)
    return top + height + 12 + len(profile["lines"]) * 36


def _summary(pdf: canvas.Canvas, profile: dict, top: float, *, accent_total: bool):
    left = 330
    right = PAGE_W - MARGIN - 10
    x = PAGE_W - MARGIN - 194
    _text(pdf, x, top, f"Subtotal: {profile['subtotal']}", size=8.5, color=profile["dark"])
    _text(pdf, x, top + 22, f"Tax: {profile['tax']}", size=8.5, color=profile["dark"])
    _box(
        pdf,
        left,
        top + 42,
        right - left + 10,
        36,
        profile["dark"] if accent_total else profile["pale"],
        radius=6,
    )
    total_color = "#F6FAFB" if accent_total else profile["dark"]
    _text(pdf, x, top + 53, f"Total: {profile['total']}", size=10.2, color=total_color, bold=True)


def _payment_block(pdf: canvas.Canvas, profile: dict, top: float, *, modern: bool):
    fill = profile["pale"] if modern else "#F3F7F8"
    _box(pdf, MARGIN, top, PAGE_W - (2 * MARGIN), 90, fill, radius=8)
    _text(pdf, MARGIN + 14, top + 12, "PAYMENT & REMITTANCE", size=7.5, color=profile["accent"], bold=True)
    _text(
        pdf,
        MARGIN + 14,
        top + 29,
        f"Payment terms: {profile['terms']}",
        size=8.2,
        color=profile["dark"],
        bold=True,
    )
    _text(
        pdf,
        MARGIN + 14,
        top + 45,
        "Use the supplier's independently verified remittance instructions.",
        size=7.8,
        color=profile["dark"],
    )
    _text(
        pdf,
        MARGIN + 14,
        top + 60,
        "Verify any beneficiary change through a known contact channel.",
        size=7.8,
        color=profile["muted"],
    )
    _text(pdf, MARGIN + 14, top + 74, f"Reference: {profile['invoice_no']}", size=7.4, color=profile["muted"])


def _brand_mark(pdf: canvas.Canvas, profile: dict, top: float):
    x = MARGIN
    y = PAGE_H - top - 49
    accent = _color(profile["accent"])
    pdf.setFillColor(accent)
    if profile["style"] == "northstar":
        pdf.roundRect(x, y, 49, 49, 10, fill=1, stroke=0)
        pdf.setStrokeColor(_color("#FFFFFF"))
        pdf.setLineWidth(2)
        pdf.line(x + 11, y + 13, x + 25, y + 37)
        pdf.line(x + 25, y + 37, x + 38, y + 13)
        pdf.line(x + 16, y + 21, x + 33, y + 21)
    else:
        pdf.circle(x + 25, y + 25, 24, fill=1, stroke=0)
        pdf.setFillColor(_color("#FFFFFF"))
        pdf.circle(x + 25, y + 25, 13, fill=1, stroke=0)
        pdf.setFillColor(_color(profile["dark"]))
        pdf.circle(x + 25, y + 25, 5, fill=1, stroke=0)


def _render_northstar(pdf: canvas.Canvas, profile: dict, kind: str):
    pdf.setFillColor(_color(profile["dark"]))
    pdf.rect(0, PAGE_H - 158, PAGE_W, 158, fill=1, stroke=0)
    pdf.setFillColor(_color(profile["accent"]))
    pdf.rect(0, PAGE_H - 158, 9, 158, fill=1, stroke=0)
    _brand_mark(pdf, profile, 33)
    _text(pdf, MARGIN + 61, 37, profile["brand"], size=16, color="#F6FAFB", bold=True)
    _text(pdf, MARGIN + 61, 57, profile["brand_line"], size=8.4, color="#D8E7EC", bold=True)
    _text(pdf, MARGIN + 61, 77, profile["strapline"], size=6.8, color="#B5CBD4")
    title = "TAX INVOICE" if kind == "invoice" else "PURCHASE ORDER"
    _text(pdf, 390, 34, title, size=19, color="#F6FAFB", bold=True)
    doc_label = "Invoice No" if kind == "invoice" else "PO No"
    doc_number = profile["invoice_no"] if kind == "invoice" else profile["po_no"]
    _text(pdf, 390, 65, f"{doc_label}: {doc_number}", size=8.3, color="#F6FAFB", bold=True)
    _text(pdf, 390, 83, f"PO No: {profile['po_no']}", size=8.3, color="#D8E7EC")
    _box(pdf, 498, 13, 57, 18, profile["accent"], radius=9)
    _text(pdf, 508, 18, "SAMPLE", size=6.4, color="#F6FAFB", bold=True)
    _field_row(
        pdf,
        profile,
        121,
        (MARGIN, 228, 417),
        text_color="#F6FAFB",
        muted_color="#D8E7EC",
    )
    _party_cards(pdf, profile, 178, style="northstar")
    _text(pdf, MARGIN, 341, profile["tax_label"], size=7.6, color=profile["muted"])
    _table(pdf, profile, 365)
    _summary(pdf, profile, 520, accent_total=True)
    _payment_block(pdf, profile, 662, modern=False)
    _text(
        pdf,
        MARGIN,
        786,
        "FICTIONAL SAMPLE - NOT A CUSTOMER OR TAX DOCUMENT",
        size=6.5,
        color=profile["muted"],
        bold=True,
    )
    _text(
        pdf,
        PAGE_W - 101,
        786,
        "INVOICE  |  1 OF 1" if kind == "invoice" else "ORDER  |  1 OF 1",
        size=6.5,
        color=profile["muted"],
    )


def _render_bluepeak(pdf: canvas.Canvas, profile: dict, kind: str):
    pdf.setFillColor(_color("#FBFAF8"))
    pdf.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    pdf.setFillColor(_color(profile["accent"]))
    pdf.rect(0, 0, 12, PAGE_H, fill=1, stroke=0)
    pdf.setFillColor(_color(profile["pale"]))
    pdf.rect(12, PAGE_H - 176, PAGE_W - 12, 176, fill=1, stroke=0)
    _brand_mark(pdf, profile, 34)
    _text(pdf, 96, 37, profile["brand"], size=14, color=profile["dark"], bold=True)
    _text(pdf, 96, 57, profile["brand_line"], size=7.7, color=profile["accent"], bold=True)
    _text(pdf, 96, 76, profile["strapline"], size=6.7, color=profile["muted"])
    title = "INVOICE" if kind == "invoice" else "PURCHASE ORDER"
    _text(pdf, 383, 29, title, size=21, color=profile["dark"], bold=True)
    doc_label = "Invoice No" if kind == "invoice" else "PO No"
    doc_number = profile["invoice_no"] if kind == "invoice" else profile["po_no"]
    _text(pdf, 383, 61, f"{doc_label}: {doc_number}", size=8, color=profile["dark"], bold=True)
    _text(pdf, 383, 79, f"PO No: {profile['po_no']}", size=8, color=profile["muted"])
    _box(pdf, 468, 109, 87, 23, profile["accent"], radius=11)
    _text(pdf, 487, 116, "SAMPLE FILE", size=6.2, color="#F6FAFB", bold=True)
    _box(pdf, MARGIN, 139, PAGE_W - (2 * MARGIN), 34, profile["dark"], radius=7)
    due_label = "PAYMENT DUE" if kind == "invoice" else "ORDER VALUE"
    _text(pdf, MARGIN + 14, 149, due_label, size=7.2, color="#E5EEF0", bold=True)
    _text(
        pdf,
        PAGE_W - MARGIN - 110,
        146,
        f"{profile['currency']}  {profile['total']}",
        size=11,
        color="#F6FAFB",
        bold=True,
    )
    _field_row(pdf, profile, 192, (MARGIN, 227, 414))
    _party_cards(pdf, profile, 236, style="bluepeak")
    _text(pdf, MARGIN, 368, profile["tax_label"], size=7.6, color=profile["muted"])
    _table(pdf, profile, 386)
    _summary(pdf, profile, 535, accent_total=False)
    _payment_block(pdf, profile, 665, modern=True)
    _text(
        pdf,
        MARGIN,
        788,
        "FICTIONAL SAMPLE - NOT A CUSTOMER OR TAX DOCUMENT",
        size=6.5,
        color=profile["muted"],
        bold=True,
    )
    _text(
        pdf,
        PAGE_W - 101,
        788,
        "INVOICE  |  1 OF 1" if kind == "invoice" else "ORDER  |  1 OF 1",
        size=6.5,
        color=profile["muted"],
    )


def build_pdf(profile: dict, *, kind: str = "invoice") -> bytes:
    if kind not in {"invoice", "purchase_order"}:
        raise ValueError("kind must be invoice or purchase_order")
    memory = BytesIO()
    pdf = canvas.Canvas(memory, pagesize=A4, pageCompression=1)
    doc_title = "Invoice" if kind == "invoice" else "Purchase Order"
    pdf.setTitle(f"Synthetic {doc_title} - {profile['invoice_no' if kind == 'invoice' else 'po_no']}")
    pdf.setAuthor("ReceivableOS synthetic showcase generator")
    pdf.setSubject("Fictional one-page English business document for OCR and invoice-PO review")
    if profile["style"] == "northstar":
        _render_northstar(pdf, profile, kind)
    else:
        _render_bluepeak(pdf, profile, kind)
    pdf.showPage()
    pdf.save()
    return memory.getvalue()


def _validate_profile(profile: dict) -> None:
    subtotal = sum((Decimal(line[4]) * Decimal(line[2]) for line in profile["lines"]), Decimal(0))
    if subtotal != Decimal(profile["subtotal"]):
        raise ValueError(f"{profile['style']} line totals do not equal the subtotal")
    if Decimal(profile["subtotal"]) + Decimal(profile["tax"]) != Decimal(profile["total"]):
        raise ValueError(f"{profile['style']} subtotal plus tax does not equal the total")
    for line in profile["lines"]:
        expected = (Decimal(line[2]) * Decimal(line[4])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if expected != Decimal(line[5]):
            raise ValueError(f"{profile['style']} line math is inconsistent for {line[0]}")


def generate(output: Path = OUTPUT) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for profile in SHOWCASE_PROFILES:
        _validate_profile(profile)
        path = output / f"{profile['style']}_invoice.pdf"
        path.write_bytes(build_pdf(profile))
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    for path in generate(args.output):
        print(path)


if __name__ == "__main__":
    main()
