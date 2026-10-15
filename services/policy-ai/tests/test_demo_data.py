"""Policy demo data (brief section 11.1): profiles, mandates and per-profile request variants.

Names, tax IDs and numbers must match the shared demo everywhere it already appears: the OCR stub, the
orchestrator's sample profiles, docs/02 section 10 and the test factory.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from factories import BUYER, SUPPLIER
from fastapi.testclient import TestClient
from wallet_mandate import WalletMandate

from app import model
from app.main import app
from app.mandate import compile_mandate

SERVICE = Path(__file__).resolve().parents[1]
REPO = SERVICE.parents[1]
FIXTURES = SERVICE / "fixtures"
SELLERS = json.loads((FIXTURES / "profiles" / "sellers.json").read_text(encoding="utf-8"))
BUYERS = json.loads((FIXTURES / "profiles" / "buyers.json").read_text(encoding="utf-8"))
VARIANTS = sorted(p.stem for p in (FIXTURES / "requests" / "variants").glob("*.json"))
client = TestClient(app)


def _load(*parts: str) -> dict:
    return json.loads(FIXTURES.joinpath(*parts).read_text(encoding="utf-8"))


def _tax_id_ok(tax_id: str) -> bool:
    """Thai 13-digit ID: check digit = (11 - sum(d_i x (14 - i)) mod 11) mod 10 over the first 12 digits."""
    if not re.fullmatch(r"\d{13}", tax_id):
        return False
    total = sum(int(d) * (13 - i) for i, d in enumerate(tax_id[:12]))
    return (11 - total % 11) % 10 == int(tax_id[12])


def test_profile_counts_and_tax_ids():
    assert len(SELLERS) == 5 and len(BUYERS) == 5
    for profile in [*SELLERS.values(), *BUYERS.values()]:
        assert _tax_id_ok(profile["tax_id"]), profile["name"]
    assert not _tax_id_ok("0105559000001")  # the primer's original ID fails the checksum


def test_demo_parties_match_the_rest_of_the_repo():
    seller, buyer = SELLERS["siam-fresh-pack"], BUYERS["mekong-basket-retail"]
    assert (seller["name"], seller["tax_id"]) == ("Siam Fresh Pack Co., Ltd.", "0105559000000")
    assert (buyer["name"], buyer["tax_id"]) == ("Mekong Basket Retail PCL", "0107559000001")
    assert seller == SUPPLIER and buyer == BUYER
    samples = json.loads(
        (REPO / "services" / "orchestrator" / "samples" / "profiles.json").read_text(encoding="utf-8")
    )
    assert samples == {"supplier_profile": seller, "buyer_profile": buyer}
    ocr = (REPO / "services" / "ocr-ai" / "datagen" / "generate.py").read_text(encoding="utf-8")
    for text in (seller["name"], seller["tax_id"], buyer["name"], buyer["tax_id"]):
        assert text in ocr  # the parties printed on OCR's generated demo invoices
    finance = (REPO / "docs" / "02-finance-domain.md").read_text(encoding="utf-8")
    for text in (
        seller["name"],
        buyer["name"],
        seller["tax_id"],
        buyer["tax_id"],
        "749,000.00",
        "524,300.00",
    ):
        assert text in finance


def test_repeat_seller_is_scenario_8():
    assert (
        _load("requests", "08_repeat_seller.json")["supplier_profile"] == SELLERS["siam-fresh-pack-after-v7"]
    )
    assert _load("requests", "01_happy.json")["supplier_profile"] == SELLERS["siam-fresh-pack"]


@pytest.mark.parametrize("name", VARIANTS)
def test_variant_requests_use_the_profile_files(name):
    body = _load("requests", "variants", f"{name}.json")
    seller = next(s for s in SELLERS.values() if s["tax_id"] == body["invoice"]["supplier"]["tax_id"])
    buyer = next(b for b in BUYERS.values() if b["tax_id"] == body["invoice"]["buyer"]["tax_id"])
    assert body["supplier_profile"] == seller and body["buyer_profile"] == buyer
    assert (
        body["invoice"]["supplier"]["name"] == seller["name"]
        and body["invoice"]["buyer"]["name"] == buyer["name"]
    )


@pytest.mark.parametrize("name", VARIANTS)
def test_variant_decisions(name):
    expected = _load("expected", "variants", f"{name}.json")
    r = client.post("/policy/decide", json=_load("requests", "variants", f"{name}.json"))
    assert r.status_code == 200
    resp = r.json()
    assert resp["decision"] == expected["decision"]
    for field in ("advance_rate", "limit", "fee_rate", "apr"):
        assert Decimal(resp[field]) == Decimal(expected[field]), field
    codes = {reason.split(":", 1)[0] for reason in resp["reasons"]}
    assert set(expected["must_contain"]) <= codes
    if resp["decision"] == "reject":
        assert any(c.startswith(("HARD.", "KO.")) for c in codes)


def test_variants_were_frozen_with_the_served_model():
    for name in VARIANTS:
        assert _load("expected", "variants", f"{name}.json")["model_version"] == model.active().version, name


def test_strict_mandate_is_compiled_from_its_sentence():
    now = datetime(2026, 10, 10, 0, 0, tzinfo=timezone(timedelta(hours=7)))
    text = (FIXTURES / "mandates" / "strict_thb.txt").read_text(encoding="utf-8").strip()
    strict = _load("mandates", "strict_thb.json")
    assert compile_mandate(text, mandate_id="mdt_strict", now=now)["mandate"] == strict
    assert strict["max_apr"] == "0.10"
    WalletMandate.model_validate(strict)
