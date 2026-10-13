"""Thai invoices whose dates are printed the way Thai businesses print them.

Same fictional invoice each time; only the issue and due date notation changes:
Buddhist Era years (CE + 543), Thai full and abbreviated month names, Thai digits,
an explicit พ.ศ. marker, and English month names for comparison.
"""

from __future__ import annotations

from datagen.reliability import render

# name: (issue date as printed, due date as printed); the true dates are 2026-10-01 and 2026-11-15.
FORMATS = {
    "iso_ce": ("2026-10-01", "2026-11-15"),
    "slash_ce": ("01/10/2026", "15/11/2026"),
    "slash_be": ("01/10/2569", "15/11/2569"),
    "iso_be": ("2569-10-01", "2569-11-15"),
    "thai_month_be": ("1 ตุลาคม 2569", "15 พฤศจิกายน 2569"),
    "thai_abbrev_be": ("1 ต.ค. 2569", "15 พ.ย. 2569"),
    "thai_abbrev_marker": ("1 ต.ค. พ.ศ. 2569", "15 พ.ย. พ.ศ. 2569"),
    "thai_digits_be": ("๑ ต.ค. ๒๕๖๙", "๑๕ พ.ย. ๒๕๖๙"),
    "english_month": ("1 Oct 2026", "15 Nov 2026"),
    "english_month_first": ("October 1, 2026", "November 15, 2026"),
}


def thai_invoice(issue: str, due: str, invoice_no: str = "INV-TH-DATES-1") -> bytes:
    fields = [
        ("Invoice No", invoice_no),
        ("PO No", "PO-TH-DATES-1"),
        ("Supplier", "บริษัท ตัวอย่างบรรจุภัณฑ์"),
        ("Buyer", "บริษัท ตัวอย่างค้าปลีก"),
        ("Supplier Tax ID", "0105559000000"),
        ("Buyer Tax ID", "0107559000001"),
        ("Supplier Country", "TH"),
        ("Buyer Country", "TH"),
        ("Supplier ID Scheme", "TAX_ID"),
        ("Buyer ID Scheme", "TAX_ID"),
        ("Issue Date", issue),
        ("Due Date", due),
        ("Currency", "THB"),
        ("Subtotal", "100.00"),
        ("Tax", "7.00"),
        ("Total", "107.00"),
        ("Tax Basis", "exclusive"),
        ("Language", "th"),
        ("Locale", "th-TH"),
    ]
    lines = [["PACK-A", "Packaging", "4", "15.00", "60.00"], ["PACK-B", "Labels", "2", "20.00", "40.00"]]
    pdf, _ = render(fields, lines, "th", 0, "")
    return pdf
