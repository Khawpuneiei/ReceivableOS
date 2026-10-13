from decimal import Decimal
from pathlib import Path

from app.models import load_mandate, load_payees
from app.settings import Settings

CONFIG = Path(__file__).resolve().parents[1] / "config"


def test_payee_registry_covers_the_mandate_allowlist():
    payees = load_payees(CONFIG / "payees.json")
    mandate = load_mandate(CONFIG / "mandate.demo.json")
    assert [p for p in mandate.payee_allowlist if p not in payees] == []
    addresses = [p.address.lower() for p in payees.values()]
    assert len(set(addresses)) == len(addresses)


def test_demo_mandate_fits_the_default_platform_ceilings(monkeypatch):
    for name in ("WALLET_MAX_TX_AMOUNT", "WALLET_DAILY_CAP"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    load_mandate(CONFIG / "mandate.demo.json").within_ceilings(s.wallet_max_tx_amount, s.wallet_daily_cap)


def test_settings_default_to_mock_and_no_secrets(monkeypatch):
    for name in ("CHAIN_MODE", "LEDGER_MODE", "DEMO_MODE", "WALLET_MAX_TX_AMOUNT"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.ledger_mode == "mock"
    assert s.demo_mode is False
    assert s.wallet_max_tx_amount == Decimal("1500000.00")
    assert s.chain_account_key_path is None
    assert s.wallet_owner_token is None
    assert s.wallet_approver_token is None
