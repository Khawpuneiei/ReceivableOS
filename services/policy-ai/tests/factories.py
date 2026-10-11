"""Builders for the shared demo request (docs/02-finance-domain.md section 10, brief section 5.3).

Siam Fresh Pack Co., Ltd. invoices Mekong Basket Retail PCL THB 749,000.00 on SFP-INV-2026-0142:
50,000 trays at 14.00 = 700,000.00 plus 7% VAT, issued 2026-10-01, due 2026-11-15, decided on 2026-10-12
(tenor 34 days, age 11).
Every call returns a fresh deep copy, so a test can edit nested keys freely.
"""

import copy
from collections.abc import Callable
from datetime import date
from pathlib import Path

import yaml

from app.engine import Ctx, build_ctx
from app.rules import DEFAULT_RULES_PATH, RuleSet, load_rules
from app.schemas import PolicyRequestExt

AS_OF = date(2026, 10, 12)

INVOICE = {
    "invoice_id": "inv_sfp_0142",
    "supplier": {"name": "Siam Fresh Pack Co., Ltd.", "tax_id": "0105559000000"},
    "buyer": {"name": "Mekong Basket Retail PCL", "tax_id": "0107559000001"},
    "invoice_no": "SFP-INV-2026-0142",
    "issue_date": "2026-10-01",
    "due_date": "2026-11-15",
    "amount": "749000.00",
    "currency": "THB",
    "line_items": [
        {"description": "Food trays", "qty": "50000", "unit_price": "14.00", "total": "700000.00"}
    ],
    "confidence": 0.95,
    "injection_flags": [],
    "fraud_score": 0.07,
    "fraud_flags": [],
    "doc_hash": "sha256:" + "ab" * 32,
    "invoice_fingerprint": "0x" + "cd" * 32,
}

SUPPLIER = {
    "name": "Siam Fresh Pack Co., Ltd.",
    "tax_id": "0105559000000",
    "wallet_address": "0xSUPPLIER",
    "years_trading": 3,
    "revenue_thb": "62000000.00",
    "invoices_financed_count": 12,
    "invoices_total": 36,
    "paid_on_time": 34,
    "historical_default_rate": 0.0,
    "dilution_rate": 0.02,
    "kyc_valid": True,
    "kyc_expiry": "2027-06-30",
    "current_exposure": "0.00",
    "facility_limit": "3000000.00",
}

BUYER = {
    "name": "Mekong Basket Retail PCL",
    "tax_id": "0107559000001",
    "internal_rating": "A-",
    "revenue_thb": "18000000000.00",
    "on_time_payment_rate": 0.97,
    "avg_days_late": 1.5,
    "buyer_confirmed": True,
    "relationship_months": 36,
    "sector": "retail",
    "current_exposure": "0.00",
    "buyer_limit": "10000000.00",
}

MANDATE = {
    "mandate_id": "mdt_001",
    "max_ltv": "0.70",
    "max_apr": "0.12",
    "max_predicted_default": "0.05",
    "human_review_above": "837500.00",
    "max_amount_per_tx": "1500000.00",
    "daily_cap": "3000000.00",
    "allowed_currency": "THB",
}


def happy_body() -> dict:
    """A full /policy/decide body for the happy path, with the demo mandate and as_of_date."""
    return copy.deepcopy(
        {
            "invoice": INVOICE,
            "supplier_profile": SUPPLIER,
            "buyer_profile": BUYER,
            "mandate": MANDATE,
            "as_of_date": AS_OF.isoformat(),
        }
    )


def ctx_for(body: dict, rules: RuleSet | None = None) -> Ctx:
    return build_ctx(PolicyRequestExt.model_validate(body), rules=rules)


def edited_rules(tmp_path: Path, edit: Callable[[dict], None]) -> RuleSet:
    """A temp copy of the active YAML with `edit` applied to the raw dict, loaded and validated."""
    raw = yaml.safe_load(DEFAULT_RULES_PATH.read_text(encoding="utf-8"))
    edit(raw)
    path = tmp_path / "policy.edited.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_rules(path)


def rule_entry(raw: dict, section: str, rule_id: str) -> dict:
    """The raw YAML entry of one rule, for edits in edited_rules()."""
    return next(r for r in raw[section] if r["id"] == rule_id)
