"""training/train.py end to end on a small generated set, written to a temp folder."""

import json
from datetime import date

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")
pytest.importorskip("sklearn")

from training import train  # noqa: E402


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    out = tmp_path_factory.mktemp("model")
    result = train.train(out / "synthetic.csv", out, date(2026, 10, 10), n=3000)
    return out, result


def test_writes_the_scorecard_and_metrics(trained):
    out, _ = trained
    card = json.loads((out / "scorecard.json").read_text(encoding="utf-8"))
    report = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert card["version"] == "credit-lr-2026-10-10.1"
    assert report["models"]["lr"]["test"]["auc"] > 0.6
    assert report["provenance"]["rows"]["train"] > report["provenance"]["rows"]["test"] > 0
