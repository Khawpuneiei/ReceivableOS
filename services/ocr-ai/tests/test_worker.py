"""Worker defaults must follow the documented English-first profile."""

import sys
from types import ModuleType

from app.ingest import ParsedDocument
from app.worker import paddle_read


def test_paddle_worker_defaults_to_english_recognizer(monkeypatch, tmp_path):
    calls = {}

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            calls.update(kwargs)

    fake_module = ModuleType("paddleocr")
    fake_module.PaddleOCR = FakePaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)
    monkeypatch.delenv("OCR_PADDLE_REC_NAME", raising=False)
    monkeypatch.setenv("OCR_PADDLE_DET_DIR", str(tmp_path / "detector"))
    monkeypatch.setenv("OCR_PADDLE_REC_DIR", str(tmp_path / "english-recognizer"))

    parsed = ParsedDocument(
        doc_hash="sha256:" + "a" * 64,
        spans=[],
        images=[],
        metadata_text=[],
        engine="image",
    )
    result = paddle_read(parsed)

    assert calls["text_recognition_model_name"] == "en_PP-OCRv5_mobile_rec"
    assert result.engine == "paddleocr:en_PP-OCRv5_mobile_rec"
