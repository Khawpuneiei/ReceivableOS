"""eval/redteam_summary.py: one row runs all four configurations and the table adds up."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

import redteam_summary  # noqa: E402


def test_approval_row_runs_every_configuration():
    row = redteam_summary.row_for("approval_cases.jsonl", "Human-approval path")
    assert (row["attacks"], row["caught"], row["unauth"]) == (4, 4, 0)
    assert (row["benign_ok"], row["benign"]) == (3, 3)
    assert row["chain_attacks"] == 4 and row["adapt_n"] == 4
    text = redteam_summary.line(row, "x")
    assert text.startswith("| x | 4 |") and "**0**" in text
