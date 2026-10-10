"""Prepare private local settings without printing or committing HMAC secrets."""

import os
import secrets
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]


def main():
    target = SERVICE / ".env.local"
    if target.exists():
        print(f"Preserved existing local configuration: {target}")
        return
    cache = SERVICE / ".cache/paddlex/official_models"
    lines = [
        f"FINGERPRINT_HMAC_KEY={secrets.token_hex(32)}",
        f"BANK_TOKEN_HMAC_KEY={secrets.token_hex(32)}",
        f"OCR_STATE_PATH={SERVICE / '.state/observations.sqlite'}",
        "OCR_PADDLE_ENABLED=1",
        "OCR_PADDLE_REC_NAME=en_PP-OCRv5_mobile_rec",
        "OCR_QWEN_ENABLED=1",
        "OCR_QWEN_URL=http://127.0.0.1:11434",
        "OCR_QWEN_MODEL=qwen3-vl:4b-instruct",
        f"OCR_PADDLE_DET_DIR={cache / 'PP-OCRv5_mobile_det'}",
        f"OCR_PADDLE_REC_DIR={cache / 'en_PP-OCRv5_mobile_rec'}",
        f"PADDLE_PDX_CACHE_HOME={SERVICE / '.cache/paddlex'}",
        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True",
        "OCR_DEVELOPMENT_MODE=0",
        "OCR_ALLOW_RESET=0",
    ]
    with open(target, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        stream.write("\n".join(lines) + "\n")
    print(f"Created private local configuration: {target}; secrets were not printed")


if __name__ == "__main__":
    main()
