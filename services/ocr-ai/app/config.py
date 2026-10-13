"""Environment settings and deterministic limits for the OCR-owned pipeline."""

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PAGES = 5
MAX_IMAGE_PIXELS = 12_000_000
MAX_TEXT_CHARS = 200_000
MAX_NUMERIC_TEXT_CHARS = 64
MAX_NUMERIC_DIGITS = 28
MAX_NUMERIC_SCALE = 12
# Exact products of two bounded coefficients plus a sum of at most 500 lines.
FINANCIAL_DECIMAL_PRECISION = 64
RENDER_DPI = 150
PARSER_TIMEOUT_SECONDS = 20
OCR_TIMEOUT_SECONDS = 90
QWEN_TIMEOUT_SECONDS = 90
MAX_OBSERVATIONS = 500
FIELD_CONFIDENCE = 0.97
REVIEW_CONFIDENCE = 0.80
GROUNDING_ROW_TOLERANCE = 3
GROUNDING_JOIN_GAP = 8
GROUNDING_ROW_OVERLAP = 0.60
FRAUD_WEIGHTS = {
    "duplicate_invoice_hash": 0.80,
    "duplicate_fingerprint": 0.80,
    "near_duplicate": 0.15,
    "math_inconsistent": 0.40,
    "po_amount_mismatch": 0.50,
    "po_party_mismatch": 0.50,
    "po_currency_mismatch": 0.50,
    "shared_bank_token": 0.15,
    "bank_account_changed": 0.25,
    "suspicious_cluster": 0.15,
    # PDF edit traces (app/forensics.py); all four together score 0.271, below Policy's 0.30 reject line.
    "pdf_text_covered": 0.15,
    "pdf_appended_text_layer": 0.05,
    "pdf_font_anomaly": 0.05,
    "pdf_incremental_update": 0.05,
}


# Public demo identifiers, never suitable for live records. Match main's dev fingerprint key.
DEV_FINGERPRINT_KEY = "receivableos-dev-fingerprint-key"
DEV_BANK_KEY = "receivableos-dev-bank-token-key"


@lru_cache(maxsize=2)
def warn_dev_key(setting: str) -> None:
    logging.getLogger("ocr-ai").warning("%s unset: using public development key; demo data only", setting)


def hmac_key(setting: str, fallback: str, development: bool) -> str | None:
    value = os.getenv(setting, "").strip()
    if not value and development:
        warn_dev_key(setting)
        return fallback
    return value or None


@dataclass(frozen=True)
class Settings:
    fingerprint_key: str | None
    bank_key: str | None
    state_path: Path
    paddle_enabled: bool
    qwen_enabled: bool
    qwen_url: str
    qwen_model: str
    development_mode: bool
    allow_reset: bool

    @classmethod
    def from_env(cls) -> "Settings":
        development = os.getenv("OCR_DEVELOPMENT_MODE", "0") == "1"
        return cls(
            fingerprint_key=hmac_key("FINGERPRINT_HMAC_KEY", DEV_FINGERPRINT_KEY, development),
            bank_key=hmac_key("BANK_TOKEN_HMAC_KEY", DEV_BANK_KEY, development),
            state_path=Path(os.getenv("OCR_STATE_PATH", str(SERVICE_DIR / ".state" / "observations.sqlite"))),
            paddle_enabled=os.getenv("OCR_PADDLE_ENABLED", "0") == "1",
            qwen_enabled=os.getenv("OCR_QWEN_ENABLED", "0") == "1",
            qwen_url=os.getenv("OCR_QWEN_URL", "http://127.0.0.1:11434"),
            qwen_model=os.getenv("OCR_QWEN_MODEL", "qwen3-vl:4b-instruct"),
            development_mode=os.getenv("OCR_DEVELOPMENT_MODE", "0") == "1",
            allow_reset=os.getenv("OCR_ALLOW_RESET", "0") == "1",
        )


# Correlated amount arithmetic and PO amount discrepancies count as one cluster family.
ANOMALY_FAMILIES = {
    "math_inconsistent": "amount",
    "po_amount_mismatch": "amount",
    "po_party_mismatch": "identity",
    "po_currency_mismatch": "currency",
    "pdf_text_covered": "tamper",
    "pdf_appended_text_layer": "tamper",
    "pdf_font_anomaly": "tamper",
    "pdf_incremental_update": "tamper",
}
