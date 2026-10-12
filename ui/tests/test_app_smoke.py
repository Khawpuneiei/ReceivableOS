"""The demo screen imports and renders in fixture mode with the network blocked."""

import json
import socket
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

UI = Path(__file__).resolve().parents[1]
APP = str(UI / "app.py")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("network blocked in the UI smoke test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setenv("UI_MODE", "fixtures")


def _text(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def test_happy_path_renders_from_fixtures():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    happy = json.loads((UI / "fixtures" / "happy.json").read_text(encoding="utf-8"))
    text = _text(at)
    assert "APPROVE" in text and "THB 524,300.00" in [m.value for m in at.metric]
    assert "FIXTURE MODE" in at.info[0].value
    assert happy["policy"]["model_version"] in at.caption[-1].value
    assert "TX-4" in text and "TX-5" not in text


def test_each_attack_button_adds_a_red_blocked_row():
    at = AppTest.from_file(APP, default_timeout=30).run()
    for case in ("a1", "a2", "a3", "a4", "a5", "a6"):
        at.button(key=f"attack_{case}").click().run()
        assert not at.exception
        assert f"BLOCKED {case.upper()}" in _text(at)
    assert "AprAboveMandate" in _text(at) and "DuplicateReceivable" in _text(at)


def test_buyer_paid_appends_the_settlement_tx():
    at = AppTest.from_file(APP, default_timeout=30).run()
    next(b for b in at.button if b.label == "Buyer paid").click().run()
    assert not at.exception
    assert "TX-5" in _text(at)


def test_invoice_text_is_escaped():
    import app as ui_app  # noqa: F401  (module import must not need a server either)

    assert ui_app.esc("<script>x</script>") == "&lt;script&gt;x&lt;/script&gt;"


def test_live_mode_without_an_orchestrator_degrades_to_fixtures(monkeypatch):
    monkeypatch.setenv("UI_MODE", "live")
    monkeypatch.setenv("ORCHESTRATOR_URL", "http://127.0.0.1:9")
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    next(b for b in at.button if b.label == "Use demo invoice").click().run()
    assert not at.exception
    assert "Orchestrator unavailable" in at.warning[0].value
    assert "APPROVE" in _text(at)  # the fixture view is still on screen
    at.button(key="attack_a3").click().run()
    assert not at.exception
    assert "BLOCKED A3" in _text(at) and "fixture: orchestrator has no attack route" in _text(at)
