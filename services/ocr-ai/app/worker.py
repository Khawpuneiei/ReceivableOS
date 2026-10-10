"""Isolated parser entry point. Never executes document links, scripts, or attachments."""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import warnings
from contextlib import redirect_stdout

import pymupdf
import zxingcpp
from PIL import Image

from app.config import MAX_IMAGE_PIXELS, MAX_PAGES, MAX_TEXT_CHARS, MAX_UPLOAD_BYTES, RENDER_DPI
from app.ingest import ParsedDocument, Span, detect_format, digest


class LimitExceeded(ValueError):
    pass


def white_on_light_background(image: pymupdf.Pixmap, box: tuple) -> bool:
    """White text on a dark header is visible; sample the surrounding render."""
    scale = RENDER_DPI / 72
    x0, y0, x1, y1 = box
    points = [(x, y) for x in (x0 - 1, (x0 + x1) / 2, x1 + 1) for y in (y0 - 1, (y0 + y1) / 2, y1 + 1)]
    pixels = [
        image.pixel(int(x * scale), int(y * scale))
        for x, y in points
        if 0 <= int(x * scale) < image.width and 0 <= int(y * scale) < image.height
    ]
    return not pixels or sum(min(pixel[:3]) >= 245 for pixel in pixels) / len(pixels) >= 0.75


def parse(content: bytes) -> ParsedDocument:
    if len(content) > MAX_UPLOAD_BYTES:
        raise LimitExceeded()
    spans, images, metadata = [], [], []
    if detect_format(content) == "pdf":
        with pymupdf.open(stream=content, filetype="pdf") as document:
            if document.needs_pass:
                raise ValueError("Encrypted document")
            if len(document) > MAX_PAGES:
                raise LimitExceeded()
            metadata = [value for value in document.metadata.values() if isinstance(value, str)]
            for page_index, page in enumerate(document):
                pixel_count = page.rect.width * page.rect.height * (RENDER_DPI / 72) ** 2
                if pixel_count > MAX_IMAGE_PIXELS:
                    raise LimitExceeded()
                if any(item[2] * item[3] > MAX_IMAGE_PIXELS for item in page.get_images(full=True)):
                    raise LimitExceeded()
                invisible_boxes = [
                    pymupdf.Rect(trace["bbox"])
                    for trace in page.get_texttrace()
                    if trace.get("type") == 3 or trace.get("opacity", 1) < 0.05
                ]
                image = page.get_pixmap(dpi=RENDER_DPI, alpha=False, colorspace=pymupdf.csRGB)
                images.append(base64.b64encode(image.tobytes("png")).decode())
                for block in page.get_text(
                    "dict",
                    flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES,
                    clip=pymupdf.INFINITE_RECT(),
                )["blocks"]:
                    for line in block.get("lines", []):
                        for raw in line["spans"]:
                            box = tuple(raw["bbox"])
                            hidden = (
                                any(
                                    box[0] >= invisible.x0 - 1
                                    and box[2] <= invisible.x1 + 1
                                    and pymupdf.Rect(box).intersects(invisible)
                                    for invisible in invisible_boxes
                                )
                                or (raw.get("color") == 0xFFFFFF and white_on_light_background(image, box))
                                or raw["size"] < 4
                                or not page.rect.contains(pymupdf.Rect(box))
                            )
                            spans.append(
                                Span(
                                    text=raw["text"],
                                    page=page_index + 1,
                                    bbox=box,
                                    confidence=1,
                                    source="pdf_text",
                                    ordinal=len(spans),
                                    size=raw["size"],
                                    color=raw.get("color"),
                                    hidden=hidden,
                                )
                            )
                for annotation in page.annots() or []:
                    metadata.append(annotation.info.get("content", ""))
    else:
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise LimitExceeded()
                if image.format not in {"PNG", "JPEG"}:
                    raise ValueError("Unsupported image")
                image.load()
                buffer = io.BytesIO()
                image.convert("RGB").save(buffer, format="PNG")
                images.append(base64.b64encode(buffer.getvalue()).decode())
    qr_payloads = []
    for encoded in images:
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as image:
            for code in zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.QRCode):
                if len(code.text) > 4096 or len(qr_payloads) >= 32:
                    raise LimitExceeded()
                qr_payloads.append(code.text)
    if (
        sum(len(span.text) for span in spans) + sum(map(len, metadata)) + sum(map(len, qr_payloads))
    ) > MAX_TEXT_CHARS:
        raise LimitExceeded()
    return ParsedDocument(
        doc_hash=digest(content),
        spans=spans,
        images=images,
        metadata_text=metadata,
        qr_payloads=qr_payloads,
        engine="pdf-text" if spans else "image",
    )


def paddle_read(parsed: ParsedDocument) -> ParsedDocument:
    # Local staged model directories are mandatory; inference must not download model weights.
    detector = os.environ.get("OCR_PADDLE_DET_DIR")
    recognizer = os.environ.get("OCR_PADDLE_REC_DIR")
    recognition_name = os.environ.get("OCR_PADDLE_REC_NAME", "en_PP-OCRv5_mobile_rec")
    if recognition_name not in {"th_PP-OCRv5_mobile_rec", "en_PP-OCRv5_mobile_rec", "PP-OCRv5_mobile_rec"}:
        raise ValueError("Unsupported staged recognition model")
    if not detector or not recognizer:
        raise ValueError("PaddleOCR model directories are not configured")
    from paddleocr import PaddleOCR

    engine = PaddleOCR(
        device="cpu",
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_detection_model_dir=detector,
        text_recognition_model_name=recognition_name,
        text_recognition_model_dir=recognizer,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
    spans = []
    if parsed.images:
        import numpy as np

    for index, encoded in enumerate(parsed.images):
        image = np.asarray(Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB"))
        for result in engine.predict(image):
            payload = result.json
            if isinstance(payload, str):
                payload = json.loads(payload)
            data = payload.get("res", payload)
            for text, score, box in zip(
                data["rec_texts"], data["rec_scores"], data["rec_boxes"], strict=True
            ):
                spans.append(
                    Span(
                        text=text,
                        confidence=float(score),
                        bbox=tuple(map(float, box)),
                        page=index + 1,
                        source="image_ocr",
                        ordinal=len(spans),
                    )
                )
    if sum(len(span.text) for span in spans) > MAX_TEXT_CHARS:
        raise LimitExceeded()
    return parsed.model_copy(update={"spans": spans, "engine": f"paddleocr:{recognition_name}"})


def main() -> None:
    try:
        content = sys.stdin.buffer.read(MAX_UPLOAD_BYTES + 1)
        # Third-party progress messages must never contaminate the structured worker channel.
        with redirect_stdout(sys.stderr):
            parsed = parse(content)
            if sys.argv[1] == "paddle":
                parsed = paddle_read(parsed)
        sys.stdout.write(parsed.model_dump_json())
    except (LimitExceeded, Image.DecompressionBombError, Image.DecompressionBombWarning):
        sys.exit(13)
    except Exception:
        # No document content, paths, or exception text is written to logs or API errors.
        sys.exit(22)


if __name__ == "__main__":
    main()
