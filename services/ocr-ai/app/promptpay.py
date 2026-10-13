"""Cross-check a Thai QR payment code (EMVCo / PromptPay) against the printed invoice.

A swapped or edited payment QR is a common way to redirect an invoice payment. QR
payloads stay untrusted and private: they never fill invoice fields, and findings
never echo the payload, the QR payee or the amount. They only report that the QR
disagrees with values the extractor already grounded in printed text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.fraud import finding
from app.models import DocumentExtraction, FraudFinding

RULE_VERSION = "thai-qr-v1"
PROMPTPAY_AID = "A000000677010111"  # Credit transfer (mobile, tax/national ID, e-wallet)
BILL_PAYMENT_AID = "A000000677010112"  # Bill payment (biller ID = 13-digit tax ID + 2-digit suffix)
CURRENCIES = {"764": "THB"}


@dataclass(frozen=True)
class ThaiQr:
    crc_valid: bool
    proxy_type: str | None  # tax_id | mobile | ewallet | None
    proxy: str | None
    amount: Decimal | None
    currency: str | None


def tlv(payload: str) -> dict[str, str] | None:
    """Parse one EMVCo TLV level; None when the structure is malformed."""
    fields, index = {}, 0
    while index < len(payload):
        if index + 4 > len(payload) or not payload[index : index + 4].isdigit():
            return None
        tag, length = payload[index : index + 2], int(payload[index + 2 : index + 4])
        value = payload[index + 4 : index + 4 + length]
        if len(value) != length:
            return None
        fields[tag] = value
        index += 4 + length
    return fields


def crc16(data: str) -> str:
    """CRC-16/CCITT-FALSE as required by EMVCo merchant-presented QR (tag 63)."""
    crc = 0xFFFF
    for byte in data.encode("ascii", "replace"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def parse_thai_qr(payload: str) -> ThaiQr | None:
    """Return the payment facts of a Thai PromptPay / bill-payment QR, else None."""
    if not payload.startswith("000201") or len(payload) > 512:
        return None
    fields = tlv(payload)
    if fields is None or "63" not in fields:
        return None
    crc_valid = len(fields["63"]) == 4 and crc16(payload[:-4]) == fields["63"].upper()
    proxy_type = proxy = None
    for tag in ("29", "30"):
        account = tlv(fields.get(tag, ""))
        if not account:
            continue
        aid = account.get("00")
        if aid == PROMPTPAY_AID:
            if "02" in account:
                proxy_type, proxy = "tax_id", account["02"]
            elif "01" in account:
                proxy_type, proxy = "mobile", account["01"]
            elif "03" in account:
                proxy_type, proxy = "ewallet", account["03"]
        elif aid == BILL_PAYMENT_AID and re.fullmatch(r"\d{15}", account.get("01", "")):
            proxy_type, proxy = "tax_id", account["01"][:13]
    if proxy_type is None:
        return None
    try:
        amount = Decimal(fields["54"]) if "54" in fields else None
    except InvalidOperation:
        amount = None
    return ThaiQr(crc_valid, proxy_type, proxy, amount, CURRENCIES.get(fields.get("53", "")))


def _tagged(code: str, reason: str, refs: list[str]) -> FraudFinding:
    return finding(code, reason, refs).model_copy(update={"rule_version": RULE_VERSION})


def qr_findings(qr_payloads: list[str], doc: DocumentExtraction) -> list[FraudFinding]:
    findings: list[FraudFinding] = []
    for payload in qr_payloads:
        qr = parse_thai_qr(payload)
        if qr is None:
            continue
        if not qr.crc_valid:
            reason = "The Thai payment QR fails its EMVCo checksum; it may be edited"
            findings.append(_tagged("qr_crc_invalid", reason, []))
        if qr.amount is not None and doc.amount.value is not None:
            printed_currency = doc.currency.value
            mismatch = qr.amount != doc.amount.value or (
                qr.currency is not None and printed_currency is not None and qr.currency != printed_currency
            )
            if mismatch:
                findings.append(
                    _tagged(
                        "qr_amount_mismatch",
                        "The payment QR carries a different amount or currency than the printed total",
                        doc.amount.evidence_refs,
                    )
                )
        supplier_id = doc.supplier.legal_identifier
        if qr.proxy_type == "tax_id" and supplier_id.value:
            if qr.proxy != supplier_id.value:
                findings.append(
                    _tagged(
                        "qr_payee_mismatch",
                        "The payment QR pays a different tax ID than the printed supplier; "
                        "possible payment-redirection (QR swap)",
                        supplier_id.evidence_refs,
                    )
                )
        elif qr.proxy_type in {"mobile", "ewallet"}:
            findings.append(
                _tagged(
                    "qr_payee_unverified",
                    "The payment QR pays a mobile number or e-wallet, "
                    "which cannot be tied to the printed supplier",
                    [],
                )
            )
    unique = {item.code: item for item in findings}
    return list(unique.values())
