"""L2 injection scanner (CLAUDE.md 7.1, 7.2). Owner: Agent AI engineer.

Every string in a request is untrusted: invoice text, OCR output, lender notes, policy reasons, memos.
The scanner catches attacks early and explains them. It is one layer, not the defence: payees come only from
the registry, the decision must be `approve`, and the chain enforces the mandate even if every rule misses.

Normalisation first (NFKC, zero-width and bidi controls removed, Latin look-alikes mapped), then base64 blobs
are decoded once and rescanned. Detectors: rules (EN, TH, ZH), an address-in-text rule and the canary.
An optional classifier can be plugged in; without one the report says `rules-v1` only.
"""

import base64
import binascii
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

ZERO_WIDTH = re.compile("[­​-‏‪-‮⁠-⁤⁦-⁩﻿]")
CONFUSABLES = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "х": "x",
        "у": "y",
        "і": "i",
        "ѕ": "s",
        "һ": "h",
        "ɡ": "g",
    }
)
BASE64_TOKEN = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
ADDRESS = re.compile(r"(?<![0-9a-f])0x[0-9a-f]{40}(?![0-9a-f])")

RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "ignore_instructions",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|your|these|the)\b"
            r".{0,40}\b(instructions?|rules?|limits?|commands?|prompts?|mandate|policy|policies)\b"
        ),
    ),
    ("role_override", re.compile(r"\b(you are now|from now on you|new instructions?|act as)\b")),
    ("fake_role_prefix", re.compile(r"(^|\s)(system|assistant|developer)\s*:")),
    (
        "money_move",
        re.compile(r"\b(send|transfer|pay|wire|release|move)\b.{0,60}\b(to|into)\b.{0,20}0x[0-9a-f]{40}"),
    ),
    ("approve_override", re.compile(r"\bapprove\b.{0,20}\b100\s*%")),
    (
        "exfiltration",
        re.compile(
            r"\b(reveal|print|show|output|echo|write)\b.{0,40}"
            r"\b(system prompt|private key|secret|api key|password|seed phrase)\b"
        ),
    ),
    ("th_ignore", re.compile(r"(ไม่ต้องสนใจ|ลืม(คำสั่ง|ทุกอย่าง)|คำสั่งก่อนหน้า|ละเว้นคำสั่ง)")),
    ("th_move_money", re.compile(r"โอน(เงิน)?(ทั้งหมด|ทั้งจำนวน|ไปที่|ไปยัง)")),
    ("zh_ignore", re.compile(r"(忽略|无视|無視)(之前|以前|所有|全部|先前)")),
    ("zh_move_money", re.compile(r"(转|轉)(账|帳|到|給|给).{0,20}0x|资金转到|把资金")),
]


class Classifier(Protocol):
    """Optional model-based detector. score() returns the probability that the text is an injection."""

    name: str

    def score(self, text: str) -> float: ...


def normalize(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw).lower()  # lowercase first so uppercase look-alikes map too
    text = ZERO_WIDTH.sub("", text).translate(CONFUSABLES)
    return " ".join(text.split())


def _decode_b64(blob: str) -> str | None:
    padded = blob + "=" * (-len(blob) % 4)
    try:
        decoded = base64.b64decode(padded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    printable = sum(ch.isprintable() or ch.isspace() for ch in decoded)
    return decoded if decoded and printable / len(decoded) >= 0.9 else None


def scan_text(raw: str, depth: int = 0) -> list[str]:
    """Rule hits for one string. Base64 blobs are decoded and rescanned once (depth 1)."""
    text = normalize(raw)
    hits = [name for name, pattern in RULES if pattern.search(text)]
    if " " in text and ADDRESS.search(text):  # free text should never carry a payout address
        hits.append("address_in_text")
    if depth == 0:
        for blob in BASE64_TOKEN.findall(raw):
            decoded = _decode_b64(blob)
            if decoded:
                hits += [f"b64:{h}" for h in scan_text(decoded, depth=1)]
    return hits


def iter_strings(obj: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from iter_strings(value, f"{path}.{key}")
    elif isinstance(obj, list | tuple):
        for i, value in enumerate(obj):
            yield from iter_strings(value, f"{path}[{i}]")


@dataclass
class ScanReport:
    hits: list[tuple[str, str]] = field(default_factory=list)  # (json path, rule)
    canary_hit: bool = False
    detectors: list[str] = field(default_factory=lambda: ["rules-v1"])

    @property
    def injection_flagged(self) -> bool:
        return bool(self.hits)


def scan_payload(payload: Any, canary: str | None = None, classifier: Classifier | None = None) -> ScanReport:
    report = ScanReport()
    for path, value in iter_strings(payload):
        report.hits += [(path, rule) for rule in scan_text(value)]
        if canary and (canary in value or canary in normalize(value)):
            report.canary_hit = True
        if classifier is not None and classifier.score(normalize(value)) >= 0.5:
            report.hits.append((path, f"classifier:{classifier.name}"))
    if classifier is not None:
        report.detectors.append(classifier.name)
    return report
