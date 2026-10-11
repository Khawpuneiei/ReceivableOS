"""L2 injection scanner (CLAUDE.md 7.1, 7.2). Owner: Agent AI engineer.

Every string in a request is untrusted: invoice text, OCR output, lender notes, policy reasons, memos.
The scanner catches attacks early and explains them. It is one layer, not the defence: payees come only from
the registry, the decision must be `approve`, and the chain enforces the mandate even if every rule misses.

Detection is by attack class, not by phrase:
- Obfuscation: each string is also scanned as decoded variants (hidden Unicode tag characters, leetspeak,
  ROT13, URL encoding, letters spaced apart). Base64 blobs are decoded once and rescanned.
- Classes: instruction override, process skipping, fake authority, payee swap, exfiltration, fake role tags.
  Proximity stops at sentence punctuation, so a match cannot span two sentences.
- Languages: per-language override and skip classes for zh, ja, ko, es, fr, vi and th.
- The whole payload is also scanned as one joined text, so an instruction split across fields is caught.
Without a classifier model the report says `rules-v1`.
"""

# ruff: noqa: E501 - multilingual rule tables are long by nature; splitting them would hurt review
import base64
import binascii
import codecs
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import unquote

ZERO_WIDTH = re.compile("[­​-‏‪-‮⁠-⁤⁦-⁩﻿]")
TAG_CHARS = re.compile("[\U000e0020-\U000e007e]")  # Unicode tag block: invisible ASCII ("ASCII smuggling")
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
LEET = str.maketrans({"1": "i", "0": "o", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
BASE64_TOKEN = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
ADDRESS = re.compile(r"(?<![0-9a-f])0x[0-9a-f]{40}(?![0-9a-f])")


def _near(left: str, right: str, gap: int) -> str:
    """`left` and `right` within `gap` characters, in either order. CJK and Thai have no spaces, so gap counts chars."""
    return rf"(?:{left}).{{0,{gap}}}(?:{right})|(?:{right}).{{0,{gap}}}(?:{left})"


# ----- English: classes with a sentence-bounded proximity window -----

EN_OVERRIDE_VERBS = (
    r"ignor(?:e|es|ed|ing)|disregard|forget|overrid(?:e|es|ing)|overlook|bypass|skip|waive|pretend|suspend|"
    r"disable|remove|lift|drop|dismiss|neglect|circumvent|sidestep|set aside|abandon|"
    r"do not follow|don'?t follow|stop following|not follow|do not apply|don'?t apply|not apply|"
    r"do not respect|don'?t respect|not respect|follow only"
)
EN_TARGETS = (
    r"instructions?|prompts?|rules?|limits?|caps?|checks?|controls?|guidance|guidelines?|policy|policies|"
    r"mandates?|approvals?|verifications?|sign-?off|reviews?|duplicate|kyb|procedures?|process|framework|"
    r"committee|threshold|ceilings?|guardrails?|safeguards?|compliance|restrictions?|requirements?|gates?|"
    r"screening|queue|warnings?|sanctions?|sanctioned"
)
EXFIL_OBJECTS = (
    r"system prompt|(?:system|internal|hidden|operating|original|initial|startup|secret|private)\s+"
    r"(?:prompts?|instructions?|rules?)|your (?:instructions?|prompts?|config|configuration)|private keys?|"
    r"signing keys?|api keys?|secret keys?|seed phrase|mnemonic|passwords?|credentials|"
    r"environment variables?|env vars?|context window|text above|above text|everything above|"
    r"everything before|word for word|verbatim|canary|secrets?"
)

# ----- Other languages: override and process-skip classes -----

ZH_VERBS = (
    "忽略|无视|無視|忽視|跳过|跳過|绕过|繞過|绕开|不遵守|不要遵守|不用遵守|不必遵守|不要理会|不理会|"
    "撤销|撤銷|取消|关闭|關閉|禁用|不遵循|不适用|不適用"
)
ZH_TARGETS = (
    "指令|指示|规则|規則|限制|限额|限額|额度|額度|上限|审核|審核|审批|審批|审查|審查|风控|風控|"
    "风险控制|風險控制|检查|檢查|校验|校驗|政策|制度|流程|权限|權限|规定|規定|担保|擔保|条件|條件"
)
ZH_SKIP = (
    "(?:不需要|不用|无需|無需|不必|免去|省略|跳过|跳過|不需).{0,8}(?:审核|審核|审批|審批|检查|檢查|风控|風控|额度|額度|复核|複核|核对|核對|校验|校驗|审查|審查)"
    "|(?:审核|審核|审批|審批|检查|檢查|风控|風控|额度|額度|复核|複核).{0,8}(?:不需要|不用|无需|無需|不必|免去|省略|跳过|跳過)"
)
JA_VERBS = "無視|無視して|無視し|従わない|従わず|回避|スキップ|省略|免除|解除|取り消し"
JA_TARGETS = "指示|指令|ルール|規則|制限|上限|限度|承認|審査|チェック|確認|リスク|ポリシー|規程|手続き|検証"
JA_SKIP = (
    "(?:チェック|審査|承認|確認|リスク管理|検証).{0,8}(?:不要|必要ありません|省略|スキップ)"
    "|(?:不要|省略|スキップ).{0,8}(?:チェック|審査|承認|確認|リスク|検証)"
)
KO_VERBS = "무시|무시하|무시하고|무시하세요|따르지|따르지 마|따르지마|적용하지|적용하지 마|우회|건너뛰|생략|면제|해제|취소"
KO_TARGETS = "지시|명령|규칙|규정|한도|제한|승인|검토|확인|리스크|정책|절차|검증|심사"
KO_SKIP = (
    "(?:검토|심사|승인|확인|리스크|검증).{0,8}(?:생략|건너뛰|불필요|필요 없|필요없|면제)"
    "|(?:생략|건너뛰|불필요|면제).{0,8}(?:검토|심사|승인|확인|리스크|검증)"
)
ES_VERBS = (
    "ignora|ignorar|ignorando|omite|omitir|olvida|olvidar|olvides|no apliques|no aplicar|no sigas|no seguir|"
    "no respetes|no respetar|salta|saltar|evita|evitar|desactiva|desactivar|elimina|eliminar|suspende|"
    "suspender|pasa por alto|pasar por alto|anula|anular"
)
ES_TARGETS = (
    "instrucciones|reglas|límites|limites|controles|control|verificación|verificacion|aprobación|aprobacion|"
    "mandato|política|politica|políticas|politicas|tope|topes|límite|limite|riesgo|guías|guias|"
    "comprobaciones|revisión|revision|requisitos"
)
ES_SKIP = (
    "(?:sin|omite|omitir|saltar|no hace falta|no es necesario|innecesari[oa]).{0,20}"
    "(?:revisión|revision|verificación|verificacion|aprobación|aprobacion|controles?|comprobaciones)"
)
FR_VERBS = (
    "ignorez|ignorer|ignore|oubliez|oublier|oublie|n'appliquez pas|n'appliquez|ne respectez pas|"
    "ne suivez pas|ne suivez|contournez|contourner|contourne|sautez|sauter|désactivez|désactiver|"
    "supprimez|supprimer|passez outre"
)
FR_TARGETS = (
    "instructions|règles|regles|limites|plafonds|plafond|contrôles|controles|contrôle|vérifications|"
    "verifications|vérification|verification|approbations|approbation|mandat|politique|garde-fous|"
    "garde fous|risques|risque|garanties|procédures|procedures"
)
FR_SKIP = (
    "(?:sans|inutile|pas besoin|pas nécessaire|pas necessaire).{0,20}"
    "(?:vérification|verification|approbation|contrôle|controle|révision|revision)"
)
VI_VERBS = (
    "bỏ qua|bo qua|phớt lờ|phot lo|không tuân theo|khong tuan theo|không làm theo|khong lam theo|"
    "vô hiệu hóa|vo hieu hoa|vượt qua|vuot qua|lách|lach|đừng tuân|dung tuan"
)
VI_TARGETS = (
    "hướng dẫn|huong dan|quy tắc|quy tac|quy định|quy dinh|giới hạn|gioi han|hạn mức|han muc|kiểm tra|"
    "kiem tra|duyệt|duyet|phê duyệt|phe duyet|rủi ro|rui ro|chính sách|chinh sach|xác minh|xac minh|"
    "hạn chế|han che"
)
VI_SKIP = (
    "(?:không cần|khong can|không cần thiết|khong can thiet).{0,15}"
    "(?:kiểm tra|kiem tra|duyệt|duyet|xác minh|xac minh|rủi ro|rui ro|giới hạn|gioi han)"
)
TH_VERBS = (
    "ไม่สนใจ|เพิกเฉย|ไม่ต้องสนใจ|ลืม|ข้าม|ไม่ทำตาม|ไม่ต้องทำตาม|ไม่ต้องดู|ไม่ต้องตรวจ|ยกเลิก|ปิดการใช้งาน|ละเว้น|ไม่ปฏิบัติตาม|เลี่ยง"
)
TH_TARGETS = "คำสั่ง|กฎ|นโยบาย|วงเงิน|ขีดจำกัด|ข้อจำกัด|การอนุมัติ|อนุมัติ|การตรวจสอบ|เงื่อนไข|ระเบียบ|กฎเกณฑ์|ลิมิต|ความปลอดภัย"
TH_SKIP = "(?:ไม่ต้อง|ไม่จำเป็น).{0,20}(?:การอนุมัติ|อนุมัติ|การตรวจสอบ|ตรวจสอบ|ดู|วงเงิน)"

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("override_en", re.compile(rf"\b(?:{EN_OVERRIDE_VERBS})\b[^.;\n]{{0,60}}\b(?:{EN_TARGETS})\b")),
    ("forget_all_en", re.compile(r"\b(?:ignore|disregard|forget)\s+(?:everything|anything)\b")),
    (
        "state_en",
        re.compile(
            rf"\b(?:{EN_TARGETS})\b[^.;\n]{{0,30}}\b(?:removed|suspended|disabled|waived|cleared|lifted|void|"
            r"outdated|not required|not needed|not applicable|does not apply|doesn'?t apply|does not exist|"
            r"doesn'?t exist|no longer appl(?:y|ies)|not in effect)\b"
        ),
    ),
    (
        "process_skip_en",
        re.compile(
            rf"\b(?:skip|skipping|bypass|omit|waive|without|no need (?:for|to)|need not|not necessary|unnecessary)\b"
            rf"[^.;\n]{{0,40}}\b(?:{EN_TARGETS})\b"
        ),
    ),
    (
        "authority_en",
        re.compile(
            r"\b(?:i|we|cfo|ceo|coo|approver|owner|admin|administrator|manager|director|supervisor|"
            r"compliance officer|risk committee)\b[^.;\n]{0,30}\b(?:authori[sz]e|authori[sz]ed|approved|"
            r"sign(?:ed)? off|granted|instruct|instructed|waive|said)\b[^.;\n]{0,50}\b(?:payment|draw|transfer|"
            r"disburse|release|skip|waive|remove|exception|mark|override|full amount|checks?|limit|cap|mandate)\b"
        ),
    ),
    (
        "payee_swap_en",
        re.compile(
            r"\b(?:send|sent|pay|paid|transfer|wire|release|remit|disburse|pay out|route)\b[^.;\n]{0,60}"
            r"\b(?:new|updated|changed|revised|alternative|different|another)\b[^.;\n]{0,25}"
            r"\b(?:account|accounts|bank|wallet|details|instructions|remittance|address|payee|beneficiary)\b"
        ),
    ),
    (
        "exfiltration_en",
        re.compile(
            r"\b(?:reveal|print|show|output|echo|write|list|dump|repeat|re-?state|restate|recite|tell|share|"
            r"paste|send|provide|display|expose|leak|disclose|give|copy|quote|reproduce|say)\b[^.;\n]{0,40}"
            rf"\b(?:{EXFIL_OBJECTS})\b"
        ),
    ),
    (
        "role_fake",
        re.compile(
            r"\[(?:system|assistant|developer|admin|override|approver)\b[^\]\n]{0,40}\]"
            r"|<\s*/?\s*(?:system|assistant|developer|admin)\s*>"
            r"|<<\s*/?\s*system\s*>>"
            r"|(?:^|\s)(?:system|assistant|developer)\s*[:：]"
            r"|\b(?:system|assistant|developer)\s+override\b"
        ),
    ),
    (
        "role_override",
        re.compile(
            r"\b(?:you are now|from now on you|new instructions?|"
            r"act as (?:the )?(?:cfo|ceo|coo|admin|administrator|system|approver|owner|developer))\b"
        ),
    ),
    (
        "money_move",
        re.compile(
            r"\b(?:send|transfer|pay|wire|release|move|remit|disburse)\b[^.;\n]{0,60}\b(?:to|into)\b"
            r"[^.;\n]{0,20}0x[0-9a-f]{40}"
        ),
    ),
    (
        "approve_override",
        re.compile(
            r"\bapprove\b[^.;\n]{0,20}\b(?:100\s*%|100 percent|everything|the full|the total|the entire)\b"
        ),
    ),
    ("zh_override", re.compile(_near(ZH_VERBS, ZH_TARGETS, 14))),
    ("zh_skip", re.compile(ZH_SKIP)),
    ("zh_move_money", re.compile(r"(?:转|轉)(?:账|帳|到|給|给).{0,20}0x|资金转到|把资金")),
    ("ja_override", re.compile(_near(JA_VERBS, JA_TARGETS, 15))),
    ("ja_skip", re.compile(JA_SKIP)),
    ("ko_override", re.compile(_near(KO_VERBS, KO_TARGETS, 15))),
    ("ko_skip", re.compile(KO_SKIP)),
    ("es_override", re.compile(_near(ES_VERBS, ES_TARGETS, 40))),
    ("es_skip", re.compile(ES_SKIP)),
    ("fr_override", re.compile(_near(FR_VERBS, FR_TARGETS, 40))),
    ("fr_skip", re.compile(FR_SKIP)),
    ("vi_override", re.compile(_near(VI_VERBS, VI_TARGETS, 30))),
    ("vi_skip", re.compile(VI_SKIP)),
    ("th_override", re.compile(_near(TH_VERBS, TH_TARGETS, 30))),
    ("th_skip", re.compile(TH_SKIP)),
    ("th_move_money", re.compile(r"โอน(เงิน)?(ทั้งหมด|ทั้งจำนวน|ไปที่|ไปยัง)")),
    ("th_ignore", re.compile(r"(ไม่ต้องสนใจ|ลืม(คำสั่ง|ทุกอย่าง)|คำสั่งก่อนหน้า|ละเว้นคำสั่ง)")),
    ("zh_ignore", re.compile(r"(忽略|无视|無視)(之前|以前|所有|全部|先前)")),
]

# Compact (letters only) matches, so spaced-out or punctuated words still hit. Kept to a few high-signal classes.
SQUASH_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "sq_override",
        re.compile(
            r"(?:ignore|disregard|forget|override|bypass|skip|waive|overlook)[a-z]{0,25}"
            r"(?:instruction|rule|limit|cap|check|mandate|policy|approval|verification|control|prompt|guidance)"
        ),
    ),
    ("sq_secret", re.compile(r"(?:systemprompt|privatekey|signingkey|apikey|seedphrase|secretkey)")),
    (
        "sq_payee_swap",
        re.compile(
            r"(?:send|pay|transfer|wire|release|remit)[a-z]{0,40}(?:new|updated|changed|revised)[a-z]{0,20}"
            r"(?:account|bank|wallet)"
        ),
    ),
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


def _variants(raw: str) -> dict[str, str]:
    """Decoded views of one string. Each one is scanned, so an encoding does not hide the instruction."""
    base = normalize(raw)
    views = {"text": base}
    hidden = "".join(chr(ord(c) - 0xE0000) for c in TAG_CHARS.findall(raw))
    if hidden:
        views["tags"] = normalize(raw + " " + hidden)  # hidden ASCII, revealed
    views["leet"] = normalize(base.translate(LEET))
    views["rot13"] = normalize(codecs.decode(base, "rot13"))
    if "%" in raw:
        views["url"] = normalize(unquote(raw))
    views["squash"] = re.sub(r"[\W_]+", "", base)  # letters only: catches spaced-out words
    return views


def scan_text(raw: str, depth: int = 0) -> list[str]:
    """Rule hits for one string across all its views. Base64 blobs are decoded and rescanned once (depth 1)."""
    hits: list[str] = []
    views = _variants(raw)
    for view, text in views.items():
        rules = SQUASH_RULES if view == "squash" else RULES
        for name, pattern in rules:
            if pattern.search(text):
                hits.append(name if view == "text" else f"{view}:{name}")
    if " " in views["text"] and ADDRESS.search(
        views["text"]
    ):  # free text should never carry a payout address
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
    detectors: list[str] = field(default_factory=lambda: ["rules-v2"])

    @property
    def injection_flagged(self) -> bool:
        return bool(self.hits)

    @property
    def rule_flagged(self) -> bool:
        return any(not rule.startswith("classifier:") for _, rule in self.hits)

    @property
    def classifier_flagged(self) -> bool:
        return any(rule.startswith("classifier:") for _, rule in self.hits)


def scan_payload(payload: Any, canary: str | None = None, classifier: Classifier | None = None) -> ScanReport:
    report = ScanReport()
    strings = list(iter_strings(payload))
    for path, value in strings:
        report.hits += [(path, rule) for rule in scan_text(value)]
        if canary and (canary in value or canary in normalize(value)):
            report.canary_hit = True
        # Free text only: scoring hashes and ids with a language model adds time and noise.
        if classifier is not None and " " in value and classifier.score(normalize(value)) >= 0.5:
            report.hits.append((path, f"classifier:{classifier.name}"))
    # Split attacks: the whole payload as one text, one string per line so no match crosses two fields.
    joined = "\n".join(value for _, value in strings)
    report.hits += [("$(joined)", f"joined:{rule}") for rule in scan_text(joined)]
    if classifier is not None:
        report.detectors.append(classifier.name)
    return report
