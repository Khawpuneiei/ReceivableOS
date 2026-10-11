"""Normalise the free-form supplier_profile / buyer_profile dicts (services/policy-ai/CLAUDE.md section 5.3).

Each field is read from a list of accepted keys (first one present wins). A field that is absent stays
MISSING so the rule that needs it is skipped and traced, never evaluated on a guessed value. The only
defaults are the ones the brief defines: exposures 0, relationship_months 0, sector "other".
Malformed values (text where a number is expected, a rate outside 0..1, an explicit tier outside A-D)
raise ValueError, which the endpoint turns into HTTP 422.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


class Missing(enum.Enum):
    """Sentinel type for "the profile did not say". Compare with `is MISSING`."""

    MISSING = "MISSING"

    def __repr__(self) -> str:
        return "MISSING"


MISSING = Missing.MISSING

TIERS = ("A", "B", "C", "D")

# External rating -> internal tier: AAA..A- -> A, BBB+..BBB- -> B, BB+..BB- -> C, B+ and below -> D.
_RATING_TO_TIER = {
    **dict.fromkeys(["AAA", "AA+", "AA", "AA-", "A+", "A", "A-"], "A"),
    **dict.fromkeys(["BBB+", "BBB", "BBB-"], "B"),
    **dict.fromkeys(["BB+", "BB", "BB-"], "C"),
    **dict.fromkeys(["B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "SD", "D"], "D"),
}


@dataclass(frozen=True)
class SupplierProfile:
    years_in_business: Decimal | Missing
    invoices_financed_count: int | Missing
    historical_default_rate: Decimal | Missing
    dilution_rate: Decimal | Missing
    on_time_ratio: Decimal | Missing
    kyc_valid: bool | Missing
    kyc_expiry: date | Missing
    current_exposure: Decimal
    facility_limit: Decimal | Missing  # MISSING = no facility cap


@dataclass(frozen=True)
class BuyerProfile:
    credit_tier: str | Missing  # "A".."D"; MISSING = no tier or rating (thin profile)
    late_payment_rate: Decimal | Missing
    avg_days_late: Decimal | Missing
    confirmed: bool | Missing
    relationship_months: int
    current_exposure: Decimal
    buyer_limit: Decimal | Missing  # MISSING = no buyer cap
    sector: str


def _first(profile: Mapping[str, Any], *keys: str) -> tuple[str, Any] | None:
    """First accepted key with a usable value. None and "" count as absent."""
    for key in keys:
        value = profile.get(key)
        if value is not None and value != "":
            return key, value
    return None


def _decimal(key: str, value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError(f"{key}: expected a number, got {type(value).__name__}")
    try:
        result = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError(f"{key}: not a number") from None
    if not result.is_finite():
        raise ValueError(f"{key}: not a finite number")
    return result


def _non_negative(key: str, value: Any) -> Decimal:
    result = _decimal(key, value)
    if result < 0:
        raise ValueError(f"{key}: must not be negative")
    return result


def _rate(key: str, value: Any) -> Decimal:
    result = _decimal(key, value)
    if not Decimal(0) <= result <= Decimal(1):
        raise ValueError(f"{key}: must be between 0 and 1")
    return result


def _count(key: str, value: Any) -> int:
    result = _non_negative(key, value)
    if result != result.to_integral_value():
        raise ValueError(f"{key}: must be a whole number")
    return int(result)


def _bool(key: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise ValueError(f"{key}: expected true or false")


def _date(key: str, value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for parse in (date.fromisoformat, lambda s: datetime.fromisoformat(s).date()):
            try:
                return parse(value.strip())
            except ValueError:
                continue
    raise ValueError(f"{key}: expected an ISO date (YYYY-MM-DD)")


def _read(profile: Mapping[str, Any], parse, *keys: str):
    found = _first(profile, *keys)
    return MISSING if found is None else parse(*found)


def _on_time_ratio(profile: Mapping[str, Any]) -> Decimal | Missing:
    found = _first(profile, "on_time_ratio")
    if found is not None:
        return _rate(*found)
    paid = _read(profile, _count, "paid_on_time")
    total = _read(profile, _count, "invoices_total")
    if paid is MISSING or total is MISSING or total == 0:
        return MISSING
    return _rate("paid_on_time / invoices_total", Decimal(paid) / Decimal(total))


def _kyc_valid(profile: Mapping[str, Any]) -> bool | Missing:
    found = _first(profile, "kyc_valid")
    if found is not None:
        return _bool(*found)
    status = _first(profile, "kyb_status")  # architecture shape: "VALID" | "EXPIRED" | ...
    if status is None:
        return MISSING
    return str(status[1]).strip().upper() == "VALID"


def normalise_supplier(profile: Mapping[str, Any] | None) -> SupplierProfile:
    p = profile or {}
    exposure = _read(p, _non_negative, "current_exposure")
    return SupplierProfile(
        years_in_business=_read(p, _non_negative, "years_in_business", "years_trading"),
        invoices_financed_count=_read(p, _count, "invoices_financed_count"),
        historical_default_rate=_read(p, _rate, "historical_default_rate"),
        dilution_rate=_read(p, _rate, "dilution_rate", "dispute_rate"),
        on_time_ratio=_on_time_ratio(p),
        kyc_valid=_kyc_valid(p),
        kyc_expiry=_read(p, _date, "kyc_expiry", "kyb_expires_at"),
        current_exposure=Decimal("0.00") if exposure is MISSING else exposure,
        facility_limit=_read(p, _non_negative, "facility_limit", "supplier_limit"),
    )


def rating_to_tier(rating: Any) -> str | Missing:
    """Map an external rating (S&P / TRIS style) to tier A-D. An unknown rating is MISSING, not a guess."""
    return _RATING_TO_TIER.get(str(rating).strip().upper(), MISSING)


def _credit_tier(profile: Mapping[str, Any]) -> str | Missing:
    found = _first(profile, "credit_tier")
    if found is not None:
        tier = str(found[1]).strip().upper()
        if tier not in TIERS:
            raise ValueError(f"credit_tier: must be one of {', '.join(TIERS)}")
        return tier
    rating = _first(profile, "credit_rating", "internal_rating")
    return MISSING if rating is None else rating_to_tier(rating[1])


def _late_payment_rate(profile: Mapping[str, Any]) -> Decimal | Missing:
    found = _first(profile, "late_payment_rate")
    if found is not None:
        return _rate(*found)
    on_time = _read(profile, _rate, "on_time_payment_rate")
    return MISSING if on_time is MISSING else Decimal(1) - on_time


def normalise_buyer(profile: Mapping[str, Any] | None) -> BuyerProfile:
    p = profile or {}
    relationship = _read(p, _count, "relationship_months")
    exposure = _read(p, _non_negative, "current_exposure")
    sector = _first(p, "sector")
    return BuyerProfile(
        credit_tier=_credit_tier(p),
        late_payment_rate=_late_payment_rate(p),
        avg_days_late=_read(p, _non_negative, "avg_days_late"),
        confirmed=_read(p, _bool, "buyer_confirmed", "buyer_acknowledged"),
        relationship_months=0 if relationship is MISSING else relationship,
        current_exposure=Decimal("0.00") if exposure is MISSING else exposure,
        buyer_limit=_read(p, _non_negative, "buyer_limit"),
        sector="other" if sector is None else str(sector[1]).strip().lower(),
    )
