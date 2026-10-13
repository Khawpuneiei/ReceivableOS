"""Wallet-internal models (CLAUDE.md 5.2, 5.4, 5.7). Owner: Agent AI engineer.

HTTP request and response models live in shared/schemas.py and are imported there, never redeclared here.
Everything that is hashed goes through canonical_json(), so one object always gives one hash.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

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
from shared.schemas import GuardCheck, PolicyDecision, WalletRequest


class DecisionFreshness(PolicyDecision):
    """PolicyDecision plus an optional expiry. Stopgap: the proper fix is a `contract:` PR that adds
    valid_until to shared PolicyDecision. It is excluded from decision_hash, which covers shared fields only.
    """

    valid_until: datetime | None = None


class ExecuteRequest(WalletRequest):
    """POST /wallet/execute body: the shared WalletRequest with the freshness-aware decision type."""

    decision: DecisionFreshness


Bytes32Hex = Annotated[str, StringConstraints(pattern=r"^0x[0-9a-fA-F]{64}$")]
Address = Annotated[str, StringConstraints(pattern=r"^0x[0-9a-fA-F]{40}$")]


def canonical_json(obj: Any) -> str:
    """Team-wide canonical form (CLAUDE.md 5.2). Pass model_dump(mode='json') output: Decimals as strings."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def keccak256_hex(text: str) -> str:
    return "0x" + keccak.new(digest_bits=256, data=text.encode("utf-8")).hexdigest()


def canonical_hash(obj: Any) -> str:
    return keccak256_hex(canonical_json(obj))


def _check_positive_money(value: Decimal) -> Decimal:
    if value <= 0:
        raise ValueError("amount must be positive")
    to_units(value)  # raises if there are more than 2 decimal places
    return value


PositiveMoney = Annotated[Decimal, AfterValidator(_check_positive_money)]


def _bounded(name: str, value: Decimal, high: Decimal) -> Decimal:
    if not Decimal(0) < value <= high:
        raise ValueError(f"{name} must be > 0 and <= {high}")
    return value


class Mandate(BaseModel):
    """The mandate the guard enforces (CLAUDE.md 5.2). Input aliases come from policy-ai's compiler.

    extra='forbid' so an unknown field fails closed instead of being silently dropped from the hash.
    """

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
    )  # inclusive: amount >= this needs a human
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
            raise ValueError("datetimes must be timezone-aware, e.g. 2026-10-10T00:00:00+07:00")
        return v

    @model_validator(mode="after")
    def _expiry_and_hash(self) -> "Mandate":
        if self.expires_at is not None and self.expires_at <= self.valid_from:
            raise ValueError("expires_at must be after valid_from")
        computed = self.compute_hash()
        if self.mandate_hash is None:
            self.mandate_hash = computed
        elif self.mandate_hash.lower() != computed:
            raise ValueError("mandate_hash does not match the mandate contents")
        return self

    def compute_hash(self) -> str:
        """keccak256 of the canonical JSON without mandate_hash (CLAUDE.md 5.2)."""
        return canonical_hash(self.model_dump(mode="json", exclude={"mandate_hash"}))

    def within_ceilings(self, max_tx: Decimal, daily_cap: Decimal) -> None:
        """Activation rule: a mandate may tighten the platform ceilings from env, never loosen them."""
        if self.max_amount_per_tx > max_tx:
            raise ValueError(f"max_amount_per_tx {self.max_amount_per_tx} is above ceiling {max_tx}")
        if self.daily_cap > daily_cap:
            raise ValueError(f"daily_cap {self.daily_cap} is above ceiling {daily_cap}")


class Payee(BaseModel):
    """One payee registry entry (CLAUDE.md 5.3). Payees are chosen by id, never by an address from text."""

    model_config = ConfigDict(extra="forbid")

    name: str
    address: Address
    # The mock KYC credential flag (scope doc section 2). Only verified payees are allowlisted on chain,
    # and the guard refuses an unverified seller. Defaults to False, so an unflagged party is not trusted.
    kyc_verified: bool = False
    # Optional end of the KYC credential, in Bangkok time. After it, the seller counts as unverified: the
    # wallet refuses the register and the draw. The chain keeps the allowlist it was given at deploy.
    # None means no expiry.
    kyc_expiry: date | None = None


def load_mandate(path: Path) -> Mandate:
    return Mandate.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_payees(path: Path) -> dict[str, Payee]:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return {party_id: Payee.model_validate(entry) for party_id, entry in raw.items()}


class _Intent(BaseModel):
    """Typed, validated input to one ledger call. Calldata is built from these fields only (CLAUDE.md 5.7)."""

    model_config = ConfigDict(frozen=True)


class RegisterIntent(_Intent):
    invoice_id: str
    invoice_fingerprint: Bytes32Hex
    doc_hash: str
    face_value: PositiveMoney
    currency: str
    due_date: date
    seller_id: str
    seller_address: Address


class ApproveIntent(_Intent):
    invoice_fingerprint: Bytes32Hex
    limit: PositiveMoney
    max_apr_bps: int = Field(ge=0, le=10_000)
    decision_hash: Bytes32Hex


class DrawIntent(_Intent):
    invoice_id: str
    invoice_fingerprint: Bytes32Hex
    mandate_id: str
    lender_id: str
    payee_id: str
    payee_address: Address
    amount: PositiveMoney
    apr_bps: int = Field(ge=0, le=10_000)
    decision_hash: Bytes32Hex
    idempotency_key: str
    lender_fee: Decimal = Field(default=Decimal("0"), ge=0)  # amount x fee_rate x tenor / 30, off chain
    platform_fee: Decimal = Field(default=Decimal("0"), ge=0)  # face x 0.003, off chain


class SettleIntent(_Intent):
    invoice_id: str
    invoice_fingerprint: Bytes32Hex
    amount_paid: PositiveMoney
    paid_at: date | None = None


class GuardResult(BaseModel):
    """Output of the guard pipeline for one intent (CLAUDE.md 5.1, 5.4).

    The signer refuses unless `passed` is True and `intent_hash` matches the intent it is asked to sign.
    """

    model_config = ConfigDict(frozen=True)

    intent_hash: Bytes32Hex
    checks: list[GuardCheck] = []
    needs_approval: bool = False  # escalation (L4), not a block

    @property
    def block_reason(self) -> str | None:
        """The first failing code, e.g. 'AprAboveMandate'."""
        return next((c.code for c in self.checks if not c.passed), None)

    @property
    def passed(self) -> bool:
        return self.block_reason is None


def intent_hash(intent: BaseModel) -> str:
    """Binds a signature to the exact intent (CLAUDE.md 5.1)."""
    return canonical_hash(intent.model_dump(mode="json"))
