"""Normalizing, multilingual detector for instruction-like text inside documents.

Document text is untrusted data. This module only *recognizes* text that tries to
address an AI or automated reviewer (override its rules, coerce a decision, tamper
with scores, redirect a payee, call a tool or leak secrets); nothing here interprets
or follows it. Detection runs on several normalized views of the text so common
obfuscations (Unicode compatibility forms, zero-width characters, Cyrillic/Greek
look-alikes, leetspeak, letter spacing, base64) reach the same rules, and on joined
visual rows so a phrase split across spans or lines is still recognized.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass

from app.layout import same_row

# Who an embedded instruction speaks to, and what it tells them to do (generic addressee rules).
# Bare role words ("Sales agent:", "Model: X200", "Reviewer: QA") are common on real invoices, so a
# human-sounding role only counts as an addressee when it carries an AI or automation qualifier.
ADDRESSEE = (
    r"(?:ai|a\.i\.|llm|gpt|chatbot|(?:ai|automated|automatic|virtual|reviewing|review|underwriting|scoring|risk|"
    r"credit|language|approval)\s+(?:agent|assistant|reviewer|underwriter|approver|model|system|bot)(?:\s+\w+)?)"
)
COMMAND = (
    r"(?:approve|fund|finance|release|waive|skip|disable|grant|classify|report|reply|respond|wire|transfer|remit|"
    r"send|ignore|accept|treat|mark|set|output|clear|fast[- ]?track|whitelist|disregard|move on|bypass|pay)"
)

RULES: tuple[tuple[str, str], ...] = (
    # Attempts to replace the reader's instructions or role.
    (
        "role_override",
        r"\b(?:ignore|disregard|forget|override|bypass)\b.{0,40}\b(?:previous|prior|above|earlier|preceding|"
        r"all|any|your|the|system|safety)\b.{0,20}\b(?:instructions?|rules?|prompts?|guidelines?|directives?|"
        r"polic(?:y|ies)|guardrails?)\b",
    ),
    ("role_override", r"\bnew (?:instructions?|rules?|task)\s*:"),
    (
        "role_override",
        r"\byou are now\b.{0,30}\b(?:assistant|agent|ai|officer|approver|admin(?:istrator)?|system|model|"
        r"reviewer|bot)\b",
    ),
    (
        "role_override",
        r"\bfrom now on\b,?\s*(?:you|respond|reply|answer|always|only|ignore|approve|output)\b",
    ),
    (
        "role_override",
        r"<\|?\s*(?:im_start|im_end|system|endoftext)\s*\|?>|\[/?inst\]|<<\s*/?sys\s*>>|"
        r"</?\s*(?:system|instructions?)\s*>",
    ),
    (
        "role_override",
        r"(?:^|[\s\"'(\[{])(?:system|assistant|developer|ai agent|ai reviewer|"
        r"note to (?:the )?ai(?: reviewer)?|to the ai)(?:\s+override)?\s*:"
        r".{0,80}?\b(?:ignore|approve(?:d(?!\s+by))?|override|bypass|skip|set|release|transfer|send|pay|grant|disable|"
        r"trusted|no (?:further )?(?:checks?|review)|do not)\b",
    ),
    # Attempts to force a credit or review outcome.
    ("decision_coercion", r"\bauto[- ]?approv(?:e|al)\b|\bpre[- ]?approved? for financing\b"),
    (
        "decision_coercion",
        r"\bapprove\b.{0,25}\b(?:invoices?|transactions?|financing|advance|loan|drawdown|100%)",
    ),
    (
        "decision_coercion",
        r"\b(?:mark|treat|classify|flag|consider|label)\b.{0,25}\bas\b.{0,10}\b(?:approved|verified|"
        r"legitimate|safe|low[- ]risk|genuine|trusted|clean|valid|whitelisted|allow[- ]?listed|exempt)\b",
    ),
    (
        "decision_coercion",
        r"\b(?:skip|bypass|disable|turn off|waive|override)\b.{0,20}\b(?:fraud|risk|kyc|aml|compliance|"
        r"security|duplicate|credit|policy|manual|human)\b.{0,15}\b(?:checks?|reviews?|screening|verification|"
        r"controls?|limits?|approval|polic(?:y|ies)|detection|scoring|matching|validation)\b",
    ),
    (
        "decision_coercion",
        r"\b(?:no|without)\s+(?:further\s+|additional\s+|more\s+|manual\s+|human\s+)?(?:checks?|reviews?|"
        r"verification)\s+(?:is\s+|are\s+)?(?:needed|required|necessary)\b",
    ),
    (
        "decision_coercion",
        r"\b(?:release|grant|fund|disburse|approve|give)\b.{0,25}\b(?:full|entire|whole|maximum|max|highest|top)\b"
        r".{0,20}\b(?:amount|advance|funds?|limit|financing)\b|"
        r"\b(?:fund|finance|release|approve)\s+(?:it\s+|this\s+\w+\s+|the\s+\w+\s+)?in full\b",
    ),
    ("decision_coercion", r"\boverride\b.{0,20}\b(?:credit|limit|polic|decision|guard|cap)"),
    # Attempts to write model or contract outputs.
    (
        "score_tampering",
        r"\b(?:fraud|risk|credit)[_ ]?score\b.{0,15}(?:=|:|\bto\b|\bis\b|\bshould be\b|\bas\b)"
        r"\s*\"?0(?:\.0+)?\b",
    ),
    (
        "score_tampering",
        r"\bset\b.{0,20}\b(?:confidence|fraud[_ ]?score|risk[_ ]?score|decision|advance[_ ]?rate|"
        r"injection[_ ]?flags|status)\b",
    ),
    (
        "score_tampering",
        r"\badvance[_ ]rate\b|\"?\b(?:decision|risk_score|fraud_score|injection_flags)\"?\s*[:=]\s*[\"\[0]",
    ),
    # Attempts to move money somewhere else.
    ("payee_redirect", r"\b0x[0-9a-f]{40}\b"),
    (
        "payee_redirect",
        r"\b(?:send|transfer|pay|wire|route|redirect|disburse|release)\b.{0,40}\b(?:advance|funds?|financing|"
        r"loan|money|payment|proceeds|drawdown)\b.{0,40}"
        r"\b(?:instead|rather than|new (?:account|payee|wallet))\b",
    ),
    (
        "payee_redirect",
        r"\b(?:change|update|replace|switch|redirect)\b.{0,20}\b(?:payee|beneficiary|bank account|"
        r"receiving account|wallet|recipient)\b.{0,10}\b(?:to|with)\b",
    ),
    # Attempts to drive tools or leak secrets.
    (
        "tool_invocation",
        r"\b(?:call|invoke|execute|trigger)\b.{0,15}\b(?:tool|function|wallet|api|endpoint|command)\b|"
        r"\bwallet\.(?:execute|approve|settle|transfer|register|confirm)\b|\b(?:function_call|tool_call|tool_use)\b",
    ),
    (
        "exfiltration",
        r"\b(?:reveal|print|output|display|leak|repeat|tell me)\b.{0,25}\b(?:system prompt|hidden prompt|"
        r"(?:your|the) instructions|api[_ ]?keys?|private keys?|seed phrase|mnemonic|secrets?|credentials|"
        r"passwords?|env(?:ironment)? variables?)\b",
    ),
    # Generic: text that addresses an AI or automated reviewer and gives it a command.
    (
        "addressed_command",
        r"(?:^|[\s\"'(\[{.,;:])(?:(?:dear|attention|attn|hey|hello|note to|message (?:for|to)|to)\s*:?\s+)?"
        r"(?:the\s+)?(?:[\w-]+\s+){0,2}"
        + ADDRESSEE
        + r"(?:\s+(?:note|notice|directive|instructions?|guidance))?"
        r"\s*[:,]\s*.{0,60}?\b" + COMMAND + r"\b",
    ),
    (
        "addressed_command",
        r"\b(?:dear|attention|attn|hey|hello)\s+(?:the\s+)?(?:[\w-]+\s+){0,2}"
        + ADDRESSEE
        + r"\b.{0,60}?\b"
        + COMMAND
        + r"\b|\b(?:instructs?|tells?|directs?|asks?|requires?)\s+(?:the|an?|any|all)\s+(?:[\w-]+\s+)?"
        + ADDRESSEE
        + r"\s+to\s+"
        + COMMAND
        + r"\b",
    ),
    # Generic: declaring the reader's rules void, or swapping its task.
    (
        "role_override",
        r"\b(?:(?:above|previous|prior|earlier|preceding|your|all|these|existing|usual|normal|standard)\s+(?:[\w-]+\s+)?"
        r"(?:rules?|instructions?|guidelines?|restrictions?|polic(?:y|ies)|checks?|guidance|constraints?)|"
        r"(?:rules?|instructions?|guidelines?|restrictions?|constraints?)\s+(?:above|before|so far))\b.{0,20}"
        r"\b(?:no longer appl(?:y|ies)|(?:are|is)\s+(?:now\s+)?"
        r"(?:void|suspended|lifted|waived|cancell?ed|revoked|disabled|obsolete)|do(?:es)?\s*n[o']t apply)\b",
    ),
    (
        "role_override",
        r"\b(?:ignore|disregard|forget)\s+(?:everything\s+|all\s+|the\s+)?(?:above|before|prior)\b",
    ),
    (
        "role_override",
        r"\byour\s+(?:task|job|role|objective|goal|instructions?)\s+(?:has|have|is|are)\s+(?:now\s+)?"
        r"(?:changed|updated|replaced|different)\b|"
        r"\binstead of\s+(?:checking|reviewing|verifying|validating|analy[sz]ing|scoring|assessing)\b.{0,50}"
        r"\b(?:reply|respond|say|answer|output|approve|mark|return|state)\b",
    ),
    (
        "score_tampering",
        r"\b(?:report|output|return|state|classify|rate|score|assess)\b.{0,25}\b(?:zero|no|nil|minimal)\s+"
        r"(?:fraud\s+)?risk\b|\b(?:classify|rate|score|assess|report)\b.{0,25}\b(?:risk|fraud)\b.{0,10}"
        r"\b(?:as|is|=)\s*(?:none|zero|nil|0|minimal)\b",
    ),
    # Thai.
    ("role_override", r"(?:ละเว้น|เพิกเฉย|ไม่ต้องสนใจ|ลืม).{0,20}(?:คำสั่ง|กฎ|ข้อกำหนด|นโยบาย)"),
    ("decision_coercion", r"ไม่ต้อง(?:ตรวจ|ทบทวน|เช็ค)|อนุมัติ(?:ทันที|อัตโนมัติ|เต็มจำนวน|ใบแจ้งหนี้นี้|สินเชื่อ)"),
    ("payee_redirect", r"(?:โอน|จ่าย|ส่ง)เงิน.{0,40}แทน|(?:เปลี่ยน|แก้ไข)(?:เลขที่)?(?:บัญชี|ผู้รับเงิน)"),
    ("score_tampering", r"(?:คะแนน|ค่า)ความเสี่ยง.{0,15}(?:เป็น|=)\s*(?:ศูนย์|0)"),
    ("decision_coercion", r"ข้าม(?:การ)?(?:ตรวจ|ทบทวน|เช็ค|คัดกรอง)"),
    (
        "addressed_command",
        r"(?:โมเดล|เอไอ|\bai\b|บอท|ระบบอัตโนมัติ|ผู้ช่วย\s*(?:ai|เอไอ))\s*[:,]?.{0,30}"
        r"(?:อนุมัติ|ระบุว่า|ข้าม|โอน|ชำระ|จ่าย|ให้ผ่าน|ปล่อย)|คุณ(?:คือ|เป็น)(?:ผู้อนุมัติ|ผู้ตรวจ|ระบบ|โมเดล|ผู้ช่วย)",
    ),
    # Simplified Chinese (experimental profile).
    (
        "role_override",
        r"忽略.{0,8}(?:指令|规则|提示)|(?:系统|助手)\s*:\s*.{0,30}(?:忽略|批准|跳过|通过|转账)",
    ),
    ("decision_coercion", r"跳过.{0,6}(?:检查|审核|验证)|批准.{0,6}(?:发票|交易|融资|贷款)"),
    (
        "addressed_command",
        r"(?:模型|AI|人工智能|机器人).{0,6}[:：,，].{0,20}(?:批准|放款|跳过|忽略|通过|转账|作废)",
    ),
)
COMPILED = tuple((category, re.compile(pattern, re.IGNORECASE | re.DOTALL)) for category, pattern in RULES)

# Latin look-alikes from Cyrillic and Greek (subset of Unicode TR39 confusables), lowercase after casefold.
CONFUSABLES = str.maketrans(
    {
        "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
        "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ӏ": "l", "һ": "h", "ԛ": "q", "ԝ": "w",
        "α": "a", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
        "ı": "i", "ɡ": "g",
    }
)  # fmt: skip
LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "|": "l"}
)
LEET_WORD = re.compile(r"[\w@$|]*[a-z][\w@$|]*")
SPACED = re.compile(r"(?<!\w)(?:\w[ .\-_·]){3,}\w(?!\w)")
BASE64 = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
MAX_DECODED = 2048


@dataclass(frozen=True)
class InjectionHit:
    category: str
    technique: str  # plain | normalized | homoglyph | leetspeak | spacing | encoded


def _visible(text: str) -> str:
    return "".join(char for char in text if unicodedata.category(char) != "Cf")


def _match(text: str) -> str | None:
    for category, pattern in COMPILED:
        if pattern.search(text):
            return category
    return None


def _views(text: str) -> list[tuple[str, str]]:
    plain = re.sub(r"\s+", " ", text).casefold()
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", _visible(text))).casefold()
    # OCR and per-glyph PDF spans can separate Thai vowels and tone marks from their base letter.
    normalized = "".join(
        char
        for index, char in enumerate(normalized)
        if not (
            char == " "
            and index + 1 < len(normalized)
            and unicodedata.category(normalized[index + 1]) == "Mn"
        )
    )
    homoglyph = normalized.translate(CONFUSABLES)
    leet = LEET_WORD.sub(
        lambda match: (
            match.group().translate(LEET) if any(c.isdigit() for c in match.group()) else match.group()
        ),
        homoglyph,
    )
    spaced = SPACED.sub(lambda match: re.sub(r"[ .\-_·]", "", match.group()), homoglyph)
    return [
        ("plain", plain),
        ("normalized", normalized),
        ("homoglyph", homoglyph),
        ("leetspeak", leet),
        ("spacing", spaced),
    ]


def detect(text: str, *, decode: bool = True) -> InjectionHit | None:
    """Return the first instruction-like match in any normalized view, else None."""
    if not text or not any(char.isalpha() for char in text):
        return None
    for technique, view in _views(text):
        category = _match(view)
        if category:
            return InjectionHit(category, technique)
    if decode:
        for token in BASE64.findall(text):
            try:
                decoded = base64.b64decode(token + "=" * (-len(token) % 4), validate=True)[:MAX_DECODED]
                decoded_text = decoded.decode("utf-8")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                continue
            if sum(char.isprintable() for char in decoded_text) < 0.9 * len(decoded_text):
                continue
            hit = detect(decoded_text, decode=False)
            if hit:
                return InjectionHit(hit.category, "encoded")
    return None


class InstructionPattern:
    """Drop-in for the old ``re.Pattern`` so layout helpers can call ``.search(text)``."""

    def search(self, text: str) -> InjectionHit | None:
        return detect(text)


def _row_text(row) -> str:
    parts: list[str] = []
    for index, span in enumerate(row):
        if index and span.bbox[0] - row[index - 1].bbox[2] > 1.5:
            parts.append(" ")
        parts.append(span.text)
    return "".join(parts)


def _unspaced(char: str) -> bool:
    name = unicodedata.name(char, "")
    return name.startswith(("THAI", "CJK")) or "IDEOGRAPH" in name


def _join(left: str, right: str) -> str:
    """Join wrapped lines; scripts written without spaces join without one."""
    if left and right and _unspaced(left[-1]) and _unspaced(right[0]):
        return left + right
    return left + " " + right


def visual_rows(spans) -> list[list]:
    """Group every span (hidden ones included) into page rows, left to right."""
    rows: list[list] = []
    for span in sorted(spans, key=lambda item: (item.page, item.source, item.bbox[1], item.bbox[0])):
        if rows and same_row(rows[-1][0], span):
            rows[-1].append(span)
        else:
            rows.append([span])
    return [sorted(row, key=lambda item: item.bbox[0]) for row in rows]


def split_hits(spans) -> list[tuple[InjectionHit, list]]:
    """Find instructions that only appear once spans in a row, or two adjacent rows, are joined."""
    rows = visual_rows(spans)
    hits: list[tuple[InjectionHit, list]] = []
    seen: set[int] = set()
    for index, row in enumerate(rows):
        candidates = [row]
        following = rows[index + 1] if index + 1 < len(rows) else None
        if following and following[0].page == row[0].page and following[0].source == row[0].source:
            height = max(1.0, row[0].bbox[3] - row[0].bbox[1])
            if following[0].bbox[1] - row[0].bbox[1] <= 2.5 * height:
                candidates.append(row + following)
        for group in candidates:
            if any(id(span) in seen for span in group):
                continue
            if any(detect(span.text) for span in group):
                continue
            text = _row_text(group) if group is row else _join(_row_text(row), _row_text(following))
            hit = detect(text)
            if hit:
                hits.append((hit, group))
                seen.update(id(span) for span in group)
                break
    return hits
