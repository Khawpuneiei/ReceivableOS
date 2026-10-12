"""Legacy integration fingerprint and independently scoped local identity tokens."""

import hashlib
import hmac
import json
import re
import unicodedata

from app.config import REVIEW_CONFIDENCE
from app.models import DocumentExtraction
from app.normalize import normalize_country, normalize_reference

HISTORY_CONTEXT_VERSION = "history-context-v1:invoice-semantic-v2:entity-v1:bank-v2:reference-numeric-runs-v1"


def history_context(fingerprint_key: str, bank_key: str | None) -> str:
    """Opaque key/recipe binding; bump the version when persisted identity rules change."""
    values = [
        HISTORY_CONTEXT_VERSION,
        token(fingerprint_key, "history-context-fingerprint", [HISTORY_CONTEXT_VERSION]),
        token(bank_key, "history-context-bank", [HISTORY_CONTEXT_VERSION]) if bank_key else None,
    ]
    return "sha256:" + hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def token(key: str, namespace: str, values: list[str]) -> str:
    if not key:
        raise ValueError("Required HMAC secret is unavailable")
    payload = json.dumps([namespace, *values], ensure_ascii=False, separators=(",", ":"))
    return hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()


def legacy_fingerprint(doc: DocumentExtraction, key: str) -> str:
    def party_key(party):
        if party.legal_identifier.value:
            return re.sub(r"\D", "", party.legal_identifier.value)
        name = (party.name.value or "").upper()
        name = re.sub(r"\b(CO LTD|COMPANY LIMITED|PLC|PCL|LTD|INC)\b", "", name)
        return "".join(char for char in name if char.isalnum())

    canonical = (
        f"v1|{party_key(doc.supplier)}|{party_key(doc.buyer)}|"
        f"{normalize_reference(doc.document_number.value)}|{doc.amount.value:.2f}|"
        f"{doc.currency.value}|{doc.issue_date.value.isoformat()}"
    )
    return "0x" + hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def entity_token(party, key: str) -> str | None:
    fields = [party.country, party.identifier_scheme, party.legal_identifier]
    if any(field.status != "present" or field.confidence < REVIEW_CONFIDENCE for field in fields):
        return None
    values = [unicodedata.normalize("NFC", field.value).strip() for field in fields]
    return "entity:v1:" + token(key, "legal-entity-v1", values)


def semantic_fingerprint(doc: DocumentExtraction, key: str) -> str | None:
    supplier, buyer = entity_token(doc.supplier, key), entity_token(doc.buyer, key)
    fields = [doc.document_number, doc.amount, doc.currency, doc.issue_date]
    if (
        not supplier
        or not buyer
        or any(field.status != "present" or field.confidence < REVIEW_CONFIDENCE for field in fields)
    ):
        return None
    # Decimal.normalize() rounds to the ambient precision; identity must not do so.
    amount = format(doc.amount.value, "f")
    if "." in amount:
        amount = amount.rstrip("0").rstrip(".")
    values = [
        supplier,
        buyer,
        normalize_reference(doc.document_number.value),
        amount,
        doc.currency.value,
        doc.issue_date.value.isoformat(),
    ]
    return "0x" + token(key, "invoice-semantic-v2", values)


def bank_token(bank: dict[str, str], key: str | None) -> str | None:
    if not bank.get("account") or bank.get("conflict"):
        return None
    if not key:
        raise ValueError("Bank-account token secret is unavailable")
    # Remove presentation separators only. Do not strip arbitrary punctuation or infer IBAN/country.
    account = re.sub(r"[\s-]", "", unicodedata.normalize("NFKC", bank["account"]))
    scheme = bank.get("scheme", "").upper()
    try:
        country = normalize_country(bank.get("country", ""))
    except ValueError:
        return None
    if scheme not in {"LOCAL", "IBAN"}:
        return None
    institution = unicodedata.normalize("NFKC", bank.get("institution", "")).strip().upper()
    if scheme.upper() == "LOCAL" and not institution:
        return None
    if scheme.upper() == "IBAN":
        account = account.upper()
    return "bank:v2:" + token(
        key,
        "bank-account-v2",
        [scheme.upper(), country.upper(), institution if scheme.upper() == "LOCAL" else "", account],
    )
