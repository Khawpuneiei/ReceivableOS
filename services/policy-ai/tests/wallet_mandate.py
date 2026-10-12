"""Test-only copy of the agent wallet's Mandate model (open PR #17, services/agent-wallet/app/models.py at
ba2278d). The compiler's `mandate` object must parse with it as is. Keep in sync with the wallet; when
PR #17 is merged, test_mandate.py also validates against the real file.
"""

import json
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from Crypto.Hash import keccak
from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from shared.money import to_units

Bytes32Hex = Annotated[str, StringConstraints(pattern=r"^0x[0-9a-fA-F]{64}$")]


def _check_positive_money(value: Decimal) -> Decimal:
    if value <= 0:
        raise ValueError("amount must be positive")
    to_units(value)
    return value


PositiveMoney = Annotated[Decimal, AfterValidator(_check_positive_money)]


def _bounded(name: str, value: Decimal, high: Decimal) -> Decimal:
    if not Decimal(0) < value <= high:
        raise ValueError(f"{name} must be > 0 and <= {high}")
    return value


class WalletMandate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mandate_id: str
    version: int = Field(default=1, ge=1)
    max_ltv: Decimal = Field(validation_alias=AliasChoices("max_ltv", "max_advance_rate"))
    max_apr: Decimal
    max_predicted_default: Decimal = Field(validation_alias=AliasChoices("max_predicted_default", "max_pd"))
    max_amount_per_tx: PositiveMoney
    daily_cap: PositiveMoney
    allowed_currency: str = "THB"
    settlement_asset: str = Field(
        default="tTHB", validation_alias=AliasChoices("settlement_asset", "allowed_settlement_asset")
    )
    require_kyb: bool = True
    require_buyer_attestation: bool = True
    duplicate_policy: str = Field(
        default="DENY", validation_alias=AliasChoices("duplicate_policy", "duplicate_invoice_policy")
    )
    human_review_above: PositiveMoney = Field(
        validation_alias=AliasChoices("human_review_above", "human_review_above_thb")
    )
    payee_allowlist: list[str]
    allowed_targets: list[str]
    valid_from: datetime
    expires_at: datetime | None = None
    approved_by: str | None = None
    mandate_hash: Bytes32Hex | None = None

    @field_validator("max_ltv")
    @classmethod
    def _ltv_bounds(cls, v: Decimal) -> Decimal:
        return _bounded("max_ltv", v, Decimal("0.90"))

    @field_validator("max_apr")
    @classmethod
    def _apr_bounds(cls, v: Decimal) -> Decimal:
        return _bounded("max_apr", v, Decimal("0.30"))

    @field_validator("max_predicted_default")
    @classmethod
    def _pd_bounds(cls, v: Decimal) -> Decimal:
        return _bounded("max_predicted_default", v, Decimal("0.20"))

    @field_validator("allowed_currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        if v != "THB":
            raise ValueError("only THB is allowed")
        return v

    @field_validator("settlement_asset")
    @classmethod
    def _asset(cls, v: str) -> str:
        if v != "tTHB":
            raise ValueError("only tTHB is allowed as settlement asset")
        return v

    @field_validator("duplicate_policy")
    @classmethod
    def _duplicates(cls, v: str) -> str:
        if v != "DENY":
            raise ValueError("duplicate_policy must be DENY")
        return v

    @field_validator("valid_from", "expires_at")
    @classmethod
    def _timezone_aware(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            raise ValueError("datetimes must be timezone-aware")
        return v

    @model_validator(mode="after")
    def _expiry_and_hash(self) -> "WalletMandate":
        if self.expires_at is not None and self.expires_at <= self.valid_from:
            raise ValueError("expires_at must be after valid_from")
        computed = self.compute_hash()
        if self.mandate_hash is None:
            self.mandate_hash = computed
        elif self.mandate_hash.lower() != computed:
            raise ValueError("mandate_hash does not match the mandate contents")
        return self

    def compute_hash(self) -> str:
        text = json.dumps(
            self.model_dump(mode="json", exclude={"mandate_hash"}), sort_keys=True, separators=(",", ":")
        )
        return "0x" + keccak.new(digest_bits=256, data=text.encode("utf-8")).hexdigest()
