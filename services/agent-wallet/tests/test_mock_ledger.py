"""Mock ledger: happy path and one test per on-chain revert (CLAUDE.md 5.6, 11). Siam Fresh Pack numbers."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from ledger.mock import MockLedger

from app.models import (
    ApproveIntent,
    DrawIntent,
    Mandate,
    RegisterIntent,
    SettleIntent,
    load_mandate,
    load_payees,
)

CONFIG = Path(__file__).resolve().parents[1] / "config"
SELLER = "0x00000000000000000000000000000000000000a1"
LENDER_B = "0x00000000000000000000000000000000000000a3"
ATTACKER = "0xbad0bad0bad0bad0bad0bad0bad0bad0bad0bad0"
FP = "0x" + "11" * 32
FP2 = "0x" + "12" * 32
FP3 = "0x" + "13" * 32
DH = "0x" + "22" * 32
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
NO_FEES = {"lender_fee": Decimal("0"), "platform_fee": Decimal("0")}


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def make_ledger(mandate: Mandate | None = None) -> tuple[MockLedger, Clock]:
    clock = Clock(NOW)
    ledger = MockLedger(clock=clock)
    m = mandate or load_mandate(CONFIG / "mandate.demo.json")
    addresses = [p.address for p in load_payees(CONFIG / "payees.json").values()]
    assert ledger.set_mandate(m, addresses, ["Registry", "Vault"]).ok
    assert ledger.deposit("lender_a", Decimal("5000000.00")).ok
    return ledger, clock


def register(ledger: MockLedger, fp: str = FP, face: str = "749000.00", seller: str = SELLER):
    return ledger.register(
        RegisterIntent(
            invoice_id=f"inv_{fp[-2:]}",
            invoice_fingerprint=fp,
            doc_hash="sha256:1",
            face_value=Decimal(face),
            currency="THB",
            due_date=date(2026, 11, 15),
            seller_id="SELLER:siam-fresh-pack",
            seller_address=seller,
        )
    )


def approve(ledger: MockLedger, fp: str = FP, limit: str = "524300.00", apr_bps: int = 1200):
    return ledger.approve(
        ApproveIntent(invoice_fingerprint=fp, limit=Decimal(limit), max_apr_bps=apr_bps, decision_hash=DH)
    )


def draw(fp: str = FP, **overrides) -> DrawIntent:
    base = {
        "invoice_id": f"inv_{fp[-2:]}",
        "invoice_fingerprint": fp,
        "mandate_id": "mdt_001",
        "lender_id": "lender_a",
        "payee_id": "SELLER:siam-fresh-pack",
        "payee_address": SELLER,
        "amount": Decimal("524300.00"),
        "apr_bps": 1095,
        "decision_hash": DH,
        "idempotency_key": f"{fp[-2:]}:draw",
        "lender_fee": Decimal("5347.86"),
        "platform_fee": Decimal("2247.00"),
    }
    base.update(overrides)
    return DrawIntent(**base)


def test_happy_path_register_approve_execute_settle():
    ledger, _ = make_ledger()
    assert register(ledger).ok
    assert approve(ledger).ok
    d = ledger.execute(draw())
    assert d.ok, d.revert_reason
    assert d.tx_hash.startswith("mock:0x")
    assert ledger.balances[SELLER] == 51670514  # seller nets 516,705.14
    assert ledger.balances["platform"] == 224700  # platform fee 2,247.00
    s = ledger.settle(
        SettleIntent(invoice_id="inv_11", invoice_fingerprint=FP, amount_paid=Decimal("749000.00"))
    )
    assert s.ok
    assert s.events["to_lender"] == 52430000  # lender principal 524,300.00
    assert s.events["to_seller"] == 22470000  # seller reserve 224,700.00


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"apr_bps": 1950}, "AprAboveMandate"),  # A3 / V5: 19.5% APR, mandate max 12%
        ({"amount": Decimal("600000.00")}, "AmountAboveLimit"),  # A4: above the approved 524,300
        ({"payee_address": ATTACKER}, "PayeeNotAllowed"),  # W01: attacker address
        ({"payee_address": LENDER_B}, "PayeeNotAllowed"),  # W02: lender id, not the bound seller
    ],
)
def test_draw_reverts_with_the_contract_string(overrides, expected):
    ledger, _ = make_ledger()
    register(ledger)
    approve(ledger)
    result = ledger.execute(draw(**overrides))
    assert result.ok is False
    assert result.revert_reason == expected
    assert result.tx_hash.startswith("mock:0x")  # reverted txs still get a hash, as on chain


def test_draw_above_the_per_tx_cap_reverts_amount_above_tx_cap():
    ledger, _ = make_ledger()  # W20: within limit and 70% advance, above the 1.5m per-tx cap
    register(ledger, face="3000000.00")
    approve(ledger, limit="1600000.00")
    result = ledger.execute(draw(amount=Decimal("1600000.00"), **NO_FEES))
    assert result.revert_reason == "AmountAboveTxCap"


def test_advance_above_seventy_percent_of_face_reverts():
    ledger, _ = make_ledger()  # V8: 80% advance = 599,200 on 749,000, approved limit allows it
    register(ledger)
    approve(ledger, limit="599200.00")
    result = ledger.execute(draw(amount=Decimal("599200.00"), **NO_FEES))
    assert result.revert_reason == "AdvanceAboveMandate"


def test_draw_on_unregistered_invoice_reverts_not_registered():
    ledger, _ = make_ledger()  # W22
    assert ledger.execute(draw()).revert_reason == "NotRegistered"


def test_draw_without_credit_approval_reverts_not_approved():
    ledger, _ = make_ledger()  # W23
    register(ledger)
    assert ledger.execute(draw()).revert_reason == "NotApproved"


def test_second_draw_on_the_same_invoice_reverts_already_drawn():
    ledger, _ = make_ledger()  # W15
    register(ledger)
    approve(ledger)
    assert ledger.execute(draw()).ok
    assert ledger.execute(draw(idempotency_key="11:draw-2", amount=Decimal("100000.00"))).revert_reason == (
        "AlreadyDrawn"
    )


def test_duplicate_registration_reverts():
    ledger, _ = make_ledger()  # A2
    assert register(ledger).ok
    assert register(ledger).revert_reason == "DuplicateReceivable"


def test_register_with_unallowlisted_seller_reverts():
    ledger, _ = make_ledger()
    assert register(ledger, seller=ATTACKER).revert_reason == "PayeeNotAllowed"


def test_expired_mandate_reverts():
    ledger, clock = make_ledger()  # A6a
    register(ledger)
    approve(ledger)
    clock.now = datetime(2026, 12, 1, tzinfo=UTC)
    assert ledger.execute(draw()).revert_reason == "MandateExpired"


def test_paused_wallet_reverts_every_agent_action():
    ledger, _ = make_ledger()  # A6b
    register(ledger)
    approve(ledger)
    assert ledger.pause(True).ok
    assert ledger.execute(draw()).revert_reason == "Paused"
    assert ledger.pause(False).ok
    assert ledger.execute(draw()).ok


def test_daily_cap_is_a_rolling_24_hour_window():
    ledger, clock = make_ledger()
    for fp in (FP, FP2, FP3):
        register(ledger, fp=fp, face="3000000.00")
        approve(ledger, fp=fp, limit="1500000.00")
    assert ledger.execute(draw(FP, amount=Decimal("1500000.00"), **NO_FEES)).ok
    assert ledger.execute(draw(FP2, amount=Decimal("1500000.00"), **NO_FEES)).ok  # 3m total, at the cap
    assert (
        ledger.execute(draw(FP3, amount=Decimal("100000.00"), **NO_FEES)).revert_reason == "DailyCapExceeded"
    )
    clock.now = NOW + timedelta(hours=25)  # the first two draws fall out of the window
    assert ledger.execute(draw(FP3, amount=Decimal("100000.00"), **NO_FEES)).ok


def test_large_draw_waits_for_human_approval_then_executes():
    ledger, _ = make_ledger()  # B03
    register(ledger, face="1400000.00")
    approve(ledger, limit="980000.00")
    pending = ledger.execute(draw(amount=Decimal("980000.00"), **NO_FEES))
    assert pending.ok
    assert pending.pending_id is not None
    assert ledger.balances.get(SELLER, 0) == 0  # nothing moved before approval
    confirmed = ledger.confirm(pending.pending_id)
    assert confirmed.ok, confirmed.revert_reason
    assert ledger.balances[SELLER] == 98000000


def test_settlement_waterfall_dilution_and_repeat():
    ledger, _ = make_ledger()  # B05, W24
    register(ledger)
    approve(ledger)
    ledger.execute(draw())
    dilute = ledger.settle(
        SettleIntent(invoice_id="inv_11", invoice_fingerprint=FP, amount_paid=Decimal("709000.00"))
    )
    assert (dilute.events["to_lender"], dilute.events["to_seller"]) == (52430000, 18470000)
    repeat = ledger.settle(
        SettleIntent(invoice_id="inv_11", invoice_fingerprint=FP, amount_paid=Decimal("749000.00"))
    )
    assert repeat.revert_reason == "AlreadySettled"


def test_settle_before_draw_reverts_not_drawn():
    ledger, _ = make_ledger()  # W25
    register(ledger)
    approve(ledger)
    settle = SettleIntent(invoice_id="inv_11", invoice_fingerprint=FP, amount_paid=Decimal("749000.00"))
    assert ledger.settle(settle).revert_reason == "NotDrawn"


def test_confirmed_draw_is_not_charged_to_the_daily_cap_twice():
    """Near a full 3m window: 1.5m is drawn, then a 1.5m held draw is confirmed. Charging the held
    draw again at confirm would count 4.5m and refuse it. It is charged once, at proposal."""
    ledger, _ = make_ledger()
    register(ledger, fp=FP2, face="3000000.00")
    approve(ledger, fp=FP2, limit="1500000.00")
    assert ledger.execute(draw(FP2, amount=Decimal("1500000.00"), **NO_FEES)).ok
    register(ledger, fp=FP, face="3000000.00")
    approve(ledger, fp=FP, limit="1500000.00")
    pending = ledger.execute(draw(FP, amount=Decimal("1500000.00"), **NO_FEES))
    assert pending.pending_id is not None  # 1.5m is at or above the 837,500 review threshold
    confirmed = ledger.confirm(pending.pending_id)
    assert confirmed.ok, confirmed.revert_reason
