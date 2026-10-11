"""The Agent demo data (data/agent): lender quotes and the attack catalogue match the code and eval sets."""

import json
from decimal import Decimal
from pathlib import Path

from app.models import load_mandate
from shared.money import fee_rate_30d_to_apr

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "agent"
SERVICE = Path(__file__).resolve().parents[1]
TESTS = SERVICE / "tests"


def load_quotes() -> dict:
    return json.loads((DATA / "lender_quotes.json").read_text(encoding="utf-8"))


def test_each_quoted_apr_is_its_fee_turned_into_apr():
    for quote in load_quotes()["quotes"]:
        assert fee_rate_30d_to_apr(Decimal(quote["fee_rate_per_30d"])) == Decimal(quote["apr"]), quote[
            "lender_id"
        ]


def test_the_selection_rule_picks_lender_a_inside_the_mandate():
    data = load_quotes()
    mandate = load_mandate(SERVICE / "config" / "mandate.demo.json")
    eligible = [q for q in data["quotes"] if Decimal(q["apr"]) <= mandate.max_apr]
    chosen = max(eligible, key=lambda q: (Decimal(q["advance_rate"]), -Decimal(q["apr"])))
    assert chosen["lender_id"] == data["chosen"] == "lender_a"


def test_the_chosen_advance_is_the_decision_limit():
    data = load_quotes()
    chosen = next(q for q in data["quotes"] if q["lender_id"] == data["chosen"])
    advance = (Decimal(data["invoice_face"]) * Decimal(chosen["advance_rate"])).quantize(Decimal("0.01"))
    assert str(advance) == data["chosen_advance"] == "524300.00"


def test_every_attack_points_at_a_real_eval_case_or_test():
    eval_rows = {}
    for path in [SERVICE / "eval" / "cases.jsonl"]:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                eval_rows.setdefault(row["id"], row)
    test_text = "\n".join(p.read_text(encoding="utf-8") for p in TESTS.glob("test_*.py"))
    catalogue = json.loads((DATA / "attack_transactions.json").read_text(encoding="utf-8"))
    for entry in catalogue:
        evidence = entry["evidence"]
        if evidence.startswith("test_"):
            assert f"def {evidence}(" in test_text, entry["id"]
            continue
        assert evidence in eval_rows, f"{entry['id']} points at missing eval case {evidence}"
        row = eval_rows[evidence]
        assert row.get("expected_code") == entry["expected_code"], entry["id"]
        assert row.get("expected_status") == entry["expected_status"], entry["id"]
