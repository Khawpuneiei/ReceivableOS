"""Explicit one-time model download; request workers require already staged model paths."""

import argparse
import os
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
os.environ["PADDLE_PDX_CACHE_HOME"] = str(SERVICE / ".cache/paddlex")
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=("en", "th", "zh"), default="en")
    arguments = parser.parse_args()
    recognition_name = {
        "en": "en_PP-OCRv5_mobile_rec",
        "th": "th_PP-OCRv5_mobile_rec",
        "zh": "PP-OCRv5_mobile_rec",
    }[arguments.language]
    from paddleocr import PaddleOCR

    PaddleOCR(
        device="cpu",
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name=recognition_name,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    print(f"Staged local PaddleOCR models under {SERVICE / '.cache/paddlex'}")


if __name__ == "__main__":
    main()
