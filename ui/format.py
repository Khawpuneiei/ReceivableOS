"""Pure display helpers for the demo screen. No Streamlit import, so they are unit-tested directly.

Money and rates arrive as decimal strings (root CLAUDE.md); they are formatted, never recomputed. The APR
shown next to a fee is the response's own `apr`, not a conversion done here.
"""

from __future__ import annotations

from decimal import Decimal

GREEN, AMBER, RED, GREY = "#1a7f37", "#b26a00", "#c62828", "#6b7280"

_STATE = {
    "approve": GREEN,
    "executed": GREEN,
    "settled": GREEN,
    "review": AMBER,
    "pending_approval": AMBER,
    "reject": RED,
    "blocked": RED,
    "failed": RED,
}


# Soft tint and dark ink per state colour, so a chip reads as icon-free text on a pale band (design system).
_TONE = {
    GREEN: ("#e6f4ec", "#0f6b35"),
    AMBER: ("#fff4e0", "#8a4b00"),
    RED: ("#fdecec", "#a61b1b"),
    GREY: ("#eef2f6", "#3b4a5c"),
}


def tone(colour: str) -> str:
    """Inline style for a chip, badge or verdict in a state colour: pale tint, dark ink, coloured edge."""
    tint, ink = _TONE.get(colour.lower(), _TONE[GREY])
    return f"background:{tint};color:{ink};border-color:{colour}"


def state_colour(state: str | None) -> str:
    """Green / amber / red by state; anything unknown is grey (never green)."""
    return _STATE.get((state or "").lower(), GREY)


def thb(amount: str | Decimal | None, currency: str = "THB") -> str:
    """'524300.00' -> 'THB 524,300.00'."""
    if amount is None:
        return "-"
    return f"{currency} {Decimal(str(amount)):,.2f}"


def pct(rate: str | Decimal | float | None, places: int = 2) -> str:
    """'0.70' -> '70.00%' (places=2), '0.0027' -> '0.27%'."""
    if rate is None:
        return "-"
    return f"{Decimal(str(rate)) * 100:.{places}f}%"


def rate_pair(fee_rate: str | None, apr: str | None) -> str:
    """'0.009', '0.1095' -> '0.90% / 30 days (10.95% APR)'."""
    if fee_rate is None:
        return "-"
    text = f"{pct(fee_rate)} / 30 days"
    return f"{text} ({pct(apr)} APR)" if apr is not None else text


def short_hash(value: str | None, keep: int = 10) -> str:
    """'mock:0xabcdef0123456789...' -> 'mock:0xabcdef01…6789'."""
    if not value:
        return "-"
    return value if len(value) <= keep + 8 else f"{value[: keep + 4]}…{value[-4:]}"


def field_source(envelope: dict, field: str) -> str:
    """Where a compiled mandate field came from: 'text', 'llm' or 'default' (shown green / green / grey)."""
    if field in envelope.get("fields_from_text", []):
        return "text"
    if field in envelope.get("fields_from_llm", []):
        return "llm"
    return "default"


def reason_code(reason: str) -> tuple[str, str]:
    """'KO.DUPLICATE: Invoice already financed' -> ('KO.DUPLICATE', 'Invoice already financed')."""
    code, _, text = reason.partition(":")
    return code.strip(), text.strip()


def gauge(pd_value: float, cap: float, scale: float | None = None) -> tuple[float, float]:
    """Positions (0-1) of the PD bar and the cap line on a bar running to `scale` (default 2 x cap)."""
    top = scale or 2 * cap
    return min(pd_value / top, 1.0), min(cap / top, 1.0)
