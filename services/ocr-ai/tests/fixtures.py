"""Disposable generated corpus shared by regressions; no checked-in render dependency."""

import tempfile
from functools import lru_cache
from pathlib import Path

from datagen.reliability import generate

_temporary = tempfile.TemporaryDirectory(prefix="ocr-regression-corpus-")


@lru_cache(maxsize=1)
def reliability_corpus() -> Path:
    root = Path(_temporary.name)
    generate(root)
    return root
