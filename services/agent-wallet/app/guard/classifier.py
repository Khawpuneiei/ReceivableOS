"""Learned injection detector for the L2 scanner (CLAUDE.md 7.2, input classifier).

Owner: Agent AI engineer.

Model: protectai/deberta-v3-base-prompt-injection-v2 (Apache-2.0), ONNX export. It is English-only and
does not detect jailbreaks (its model card says so). It adds a signal on top of the rules, not a replacement.

Loading is local only. The weights are read from INJECTION_MODEL_DIR and must match the pinned SHA-256 below,
so a swapped or corrupted file is refused. Nothing is downloaded at runtime.
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL_NAME = "protectai-deberta-v3-v2-onnx"
MODEL_FILE = "model.onnx"
MODEL_SHA256 = "f0ea7f239f765aedbde7c9e163a7cb38a79c5b8853d3f76db5152172047b228c"
MAX_TOKENS = 512


class OnnxInjectionClassifier:
    name = MODEL_NAME

    def __init__(self, model_dir: Path) -> None:
        config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        id2label = {int(k): str(v).upper() for k, v in config["id2label"].items()}
        self._injection_ids = [i for i, label in id2label.items() if label == "INJECTION"]
        if not self._injection_ids:
            raise ValueError("model config has no INJECTION label")
        self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=MAX_TOKENS)
        self._session = ort.InferenceSession(str(model_dir / MODEL_FILE), providers=["CPUExecutionProvider"])

    def score(self, text: str) -> float:
        """Probability that the text is an injection, from the softmax over the two logits."""
        encoded = self._tokenizer.encode(text)
        feed = {
            "input_ids": np.array([encoded.ids], dtype=np.int64),
            "attention_mask": np.array([encoded.attention_mask], dtype=np.int64),
        }
        logits = self._session.run(None, feed)[0][0]
        exp = np.exp(logits - logits.max())
        probs = exp / exp.sum()
        return float(sum(probs[i] for i in self._injection_ids))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def load_classifier(model_dir: str) -> OnnxInjectionClassifier:
    """Loads the classifier once per process. Raises if the weights do not match the pinned checksum."""
    path = Path(model_dir) / MODEL_FILE
    if not path.is_file():
        raise FileNotFoundError(f"injection model not found at {path}")
    actual = _sha256(path)
    if actual != MODEL_SHA256:
        raise ValueError(f"injection model checksum mismatch: {actual} != {MODEL_SHA256}")
    return OnnxInjectionClassifier(Path(model_dir))
