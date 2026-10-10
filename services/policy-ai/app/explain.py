"""POST /policy/explain: a short plain-English explanation of a finished decision (stretch, CLAUDE.md §9).

The input is decision JSON only, never invoice text. The explanation is built from **facts**: the decision's
numbers, formatted once here, and the YAML messages of its reason codes. The caller's reason *text* is never
used, because a tampered `reasons` entry is untrusted (wallet threat T3), and codes the YAML doesn't know are
dropped. So nothing the caller types can reach the output or a prompt.

Without an LLM (the default) the template text is returned. With one configured (app/llm_client.py), the LLM
may rephrase the same facts, and its text is used only if it passes every check:
- 80 words or fewer;
- every number in it is one of the facts' numbers;
- it names the actual outcome and not the opposite one;
- no addresses or links.
Anything else, or any LLM failure, returns the template text with a warning.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from decimal import Decimal

from pydantic import Field

from app.rules import RuleSet, active_rules
from shared.money import fee_rate_30d_to_apr
from shared.schemas import Decision, PolicyDecision

MAX_WORDS = 80
FEE_PERIOD_DAYS = 30  # fee_rate is per 30 days (root CLAUDE.md)
MAX_REASONS = 3
_CODE = re.compile(r"^[A-Z]+\.[A-Z0-9_]+$")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_FORBIDDEN = re.compile(r"0x[0-9a-fA-F]|https?://|www\.", re.IGNORECASE)
# reasons shown per outcome: what blocked it, what needs a person, or what shaped the terms
_SHOWN = {
    Decision.reject: ("HARD.", "KO."),
    Decision.review: ("HARD.", "REVIEW.", "KO."),
    Decision.approve: ("TERMS.",),
}
_MUST = {
    Decision.approve: ("approv",),
    Decision.review: ("review", "check"),
    Decision.reject: ("not financed", "reject", "declin"),
}
_MUST_NOT = {
    Decision.approve: ("reject", "declin", "not financed"),
    Decision.review: (),
    Decision.reject: ("approv",),
}
SYSTEM = (
    "You explain a finished invoice-financing decision to a small-business owner in plain English. "
    "Use only the facts in the user's JSON. At most 80 words. Use only numbers that appear in the facts. "
    "Say clearly whether the invoice is approved, needs a person to review it, or is not financed. "
    "No advice, no promises, no addresses, no links."
)


class ExplainRequest(PolicyDecision):
    """A PolicyDecision (or PolicyDecisionExt) JSON; the extra fields below are optional."""

    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    tenor_days: int | None = Field(default=None, ge=0, le=3650)
    fee_amount: Decimal | None = Field(default=None, ge=0)


def _percent(rate: Decimal | float, places: int = 2) -> str:
    """0.70 -> '70%', 0.009 -> '0.90%', 0.002702 -> '0.27%'."""
    value = Decimal(str(rate)) * 100
    text = f"{value:.{places}f}"
    whole = text.split(".")[0]
    return f"{whole}%" if value == Decimal(whole) else f"{text}%"


def _money(amount: Decimal, currency: str | None) -> str:
    return f"{currency + ' ' if currency else ''}{Decimal(amount):,.2f}"


def _messages(rules: RuleSet) -> dict[str, str]:
    out = {r.id: r.message for r in rules.predicate_rules()}
    out.update({c.id: c.message for c in rules.terms.caps})
    out[rules.pricing.id] = rules.pricing.message
    return out


def _codes(reasons: list) -> list[str]:
    codes = []
    for r in reasons:
        code = r.code if hasattr(r, "code") else str(r).partition(":")[0].strip()
        if _CODE.match(code) and code not in codes:
            codes.append(code)
    return codes


def facts(d: ExplainRequest, rules: RuleSet | None = None) -> dict:
    """Every fact the explanation may use, formatted once, from numbers, the outcome and YAML text only."""
    known = _messages(rules or active_rules())
    shown = _SHOWN[d.decision]
    reasons = [known[c] for c in _codes(d.reasons) if c in known and c.startswith(shown)]
    out: dict = {"outcome": d.decision.value, "reasons": reasons}
    if d.decision != Decision.reject:
        apr = d.apr if d.apr is not None else fee_rate_30d_to_apr(d.fee_rate)
        out |= {
            "advance": _percent(d.advance_rate),
            "advance_amount": _money(d.limit, d.currency),
            "fee": f"{_percent(d.fee_rate)} per {FEE_PERIOD_DAYS} days",
            "apr": _percent(apr),
            "buyer_default_chance": _percent(d.risk_score),
        }
        if d.tenor_days is not None and d.fee_amount is not None:
            out["fee_total"] = f"{_money(d.fee_amount, d.currency)} for {d.tenor_days} days"
    return out


def _sentence(items: list[str]) -> str:
    return "; ".join(m.rstrip(".") for m in items)


def template(f: dict) -> str:
    """The deterministic explanation; drops reasons until it fits in MAX_WORDS."""
    for n in range(min(len(f["reasons"]), MAX_REASONS), -1, -1):
        why = _sentence(f["reasons"][:n])
        if f["outcome"] == "reject":
            text = f"Not financed{': ' + why if why else ''}. No money will move for this invoice."
        else:
            terms = (
                f"an advance of {f['advance']} of the invoice ({f['advance_amount']}) at {f['fee']} "
                f"({f['apr']} a year)" + (f", a fee of {f['fee_total']}" if "fee_total" in f else "")
            )
            risk = f"The predicted chance that the buyer does not pay is {f['buyer_default_chance']}."
            if f["outcome"] == "approve":
                text = f"Approved: {terms}. {risk}" + (f" Terms set by: {why}." if why else "")
            else:
                text = (
                    f"Needs a person to review it before any money moves{': ' + why if why else ''}. "
                    f"If they approve, the terms would be {terms}. {risk}"
                )
        if len(text.split()) <= MAX_WORDS:
            return text
    return text


def _numbers(text: str) -> set[Decimal]:
    return {Decimal(n.replace(",", "")).normalize() for n in _NUMBER.findall(text)}


def check(text: str, f: dict) -> str | None:
    """None if `text` may be shown for these facts, else why not."""
    lowered = text.lower()
    if not text.strip() or len(text.split()) > MAX_WORDS:
        return f"not 1-{MAX_WORDS} words"
    if _FORBIDDEN.search(text):
        return "contains an address or link"
    unknown = _numbers(text) - _numbers(json.dumps(f))
    if unknown:
        return "uses numbers that are not in the decision: " + ", ".join(sorted(map(str, unknown)))
    outcome = Decision(f["outcome"])
    if not any(w in lowered for w in _MUST[outcome]) or any(w in lowered for w in _MUST_NOT[outcome]):
        return "does not state the decision's outcome"
    return None


def explain(
    d: ExplainRequest,
    complete: Callable[[list[dict], dict], dict | None] | None = None,
    rules: RuleSet | None = None,
) -> dict:
    f = facts(d, rules)
    fallback = template(f)
    if complete is None:
        from app import llm_client  # imported here so /policy/decide never loads it

        if llm_client.settings() is None:
            return {"explanation": fallback, "source": "template", "warnings": []}
        complete = llm_client.complete
    schema = {
        "type": "object",
        "properties": {"explanation": {"type": "string", "maxLength": 800}},
        "required": ["explanation"],
        "additionalProperties": False,
    }
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(f)}]
    reply = complete(messages, schema)
    text = reply.get("explanation") if isinstance(reply, dict) else None
    if not isinstance(text, str):
        return {"explanation": fallback, "source": "template", "warnings": ["no usable LLM reply"]}
    text = " ".join(text.split())
    problem = check(text, f)
    if problem:
        return {"explanation": fallback, "source": "template", "warnings": [f"LLM text rejected: {problem}"]}
    return {"explanation": text, "source": "llm", "warnings": []}
