"""Environment settings and deterministic limits for the OCR-owned pipeline."""

import os
from dataclasses import dataclass
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
    "suspicious_cluster": 0.15,
}


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
        return cls(
            fingerprint_key=os.getenv("FINGERPRINT_HMAC_KEY"),
            bank_key=os.getenv("BANK_TOKEN_HMAC_KEY"),
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
}
