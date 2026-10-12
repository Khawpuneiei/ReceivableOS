"""CHAIN_MODE is the team's name for the chain switch. LEDGER_MODE is still read for older .env files."""

import pytest
from pydantic import ValidationError

from app.settings import Settings


@pytest.mark.parametrize("name", ["CHAIN_MODE", "LEDGER_MODE"])
def test_either_name_selects_fisco(monkeypatch, name):
    monkeypatch.delenv("CHAIN_MODE", raising=False)
    monkeypatch.delenv("LEDGER_MODE", raising=False)
    monkeypatch.setenv(name, "fisco")
    assert Settings(_env_file=None).ledger_mode == "fisco"


def test_the_constructor_keyword_still_works():
    assert Settings(_env_file=None, ledger_mode="fisco").ledger_mode == "fisco"


def test_an_unknown_chain_is_refused(monkeypatch):
    monkeypatch.delenv("LEDGER_MODE", raising=False)
    monkeypatch.setenv("CHAIN_MODE", "evm")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
