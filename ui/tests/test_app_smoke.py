"""The demo site imports and renders every page in fixture mode with the network blocked."""

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


def _open(at: AppTest, page: str) -> AppTest:
    """Go to one of the top-nav pages (ui/views/<page>.py), keeping this session's state."""
    return at.switch_page(f"views/{page}.py").run()


def test_happy_path_renders_from_fixtures():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    happy = json.loads((UI / "fixtures" / "happy.json").read_text(encoding="utf-8"))
    assert "Write the rule once" in _text(at) and "THB 524,300.00" in _text(at)  # Home's hero
    assert "FIXTURE MODE" in at.info[0].value
    assert happy["policy"]["model_version"] in at.caption[-1].value
    _open(at, "decision")
    assert "APPROVE" in _text(at) and "THB 524,300.00" in [m.value for m in at.metric]
    _open(at, "ledger")
    assert "TX-4" in _text(at) and "TX-5" not in _text(at)


@pytest.mark.parametrize("page", ["home", "invoice", "decision", "rule", "ledger", "security"])
def test_every_page_renders_with_the_status_banner_and_footer(page):
    at = _open(AppTest.from_file(APP, default_timeout=30).run(), page)
    assert not at.exception
    assert "FIXTURE MODE" in at.info[0].value and "policy_version" in at.caption[-1].value


def test_each_attack_button_adds_a_red_blocked_row():
    at = _open(AppTest.from_file(APP, default_timeout=30).run(), "security")
    for case in ("a1", "a2", "a3", "a4", "a5", "a6"):
        at.button(key=f"attack_{case}").click().run()
        assert not at.exception
        assert f"BLOCKED {case.upper()}" in _text(at)
    assert "AprAboveMandate" in _text(at) and "DuplicateReceivable" in _text(at)


def test_run_all_six_attacks_adds_six_blocked_rows():
    at = _open(AppTest.from_file(APP, default_timeout=30).run(), "security")
    at.button(key="attack_all").click().run()
    assert not at.exception
    assert all(f"BLOCKED {case}" in _text(at) for case in ("A1", "A2", "A3", "A4", "A5", "A6"))


def test_buyer_paid_appends_the_settlement_tx():
    at = _open(AppTest.from_file(APP, default_timeout=30).run(), "ledger")
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
    at.button(key="case_happy").click().run()
    assert not at.exception
    assert "Orchestrator unavailable" in at.warning[0].value
    assert "APPROVE" in _text(_open(at, "decision"))  # the fixture view is still on screen
    _open(at, "security").button(key="attack_a3").click().run()
    assert not at.exception
    assert "BLOCKED A3" in _text(at) and "fixture: orchestrator has no attack route" in _text(at)


def test_live_mode_says_what_it_will_call_before_any_run(monkeypatch):
    monkeypatch.setenv("UI_MODE", "live")
    monkeypatch.setenv("ORCHESTRATOR_URL", "http://127.0.0.1:9")
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert "SAVED DEMO" in at.info[0].value and "127.0.0.1:9" in at.info[0].value


def test_each_demo_case_posts_its_own_pdf_and_a_duplicate_runs_happy_first(monkeypatch):
    import client as orch

    sent = []

    def fake_run_flow(self, content, filename, mandate_id="mdt_001"):
        sent.append(filename)
        raise orch.Unavailable("stub")

    monkeypatch.setenv("UI_MODE", "live")
    monkeypatch.setattr(orch.Orchestrator, "run_flow", fake_run_flow)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button(key="case_duplicate").click().run()
    assert sent == ["01_happy.pdf", "04_duplicate.pdf"]  # the happy run failed, so it isn't marked as run
    at.button(key="case_injected").click().run()
    assert sent[-1] == "02_injected.pdf" and not at.exception


def test_attack_rows_show_live_or_saved_and_only_the_deciding_policy_codes():
    import app as ui_app

    a1 = json.loads((UI / "fixtures" / "a1.json").read_text(encoding="utf-8"))
    live = ui_app.attack_row_html({**a1, "label": "live", "chain_ref": None, "block_reason": "NotApproved"})
    assert "LIVE" in live and "stopped before the ledger" in live and "no recorded credit approval" in live
    assert "HARD.INJECTION" in live and "TERMS.MANDATE_CAP" not in live
    saved = ui_app.attack_row_html({**a1, "label": "fixture: orchestrator has no attack route"})
    assert "SAVED" in saved and "LIVE" not in saved


def test_the_verdict_says_saved_demo_when_nothing_ran_live():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert "Funded inside the rules (saved demo)" in _text(at)


@pytest.mark.parametrize(
    ("case", "headline"),
    [
        ("happy", "Funded inside the rules"),
        ("injected", "Sent to a person"),
        ("inflated", "Rejected"),
        ("duplicate", "Stopped: duplicate invoice"),
    ],
)
def test_fixture_mode_shows_the_saved_run_of_each_case(case, headline):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button(key=f"case_{case}").click().run()
    assert not at.exception
    assert "SAVED RUN" in at.info[0].value
    assert headline in _text(at) and "(saved demo)" in _text(at)


def test_live_failure_falls_back_to_the_saved_run_of_the_same_case(monkeypatch):
    monkeypatch.setenv("UI_MODE", "live")
    monkeypatch.setenv("ORCHESTRATOR_URL", "http://127.0.0.1:9")
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button(key="case_inflated").click().run()
    assert not at.exception
    assert "saved run of this case" in at.warning[0].value
    assert "Rejected" in _text(at) and "SAVED RUN: Inflated amount" in at.info[0].value


def test_cases_without_a_saved_run_or_pdf_are_not_offered():
    at = AppTest.from_file(APP, default_timeout=30).run()
    keys = {b.key for b in at.button if b.key and b.key.startswith("case_")}
    assert {"case_happy", "case_duplicate"} <= keys and "case_qr_swap" not in keys  # no saved QR-swap run yet


def test_judge_mode_runs_every_case_and_lists_one_verdict_each():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.button(key="run_all").click().run()
    assert not at.exception
    text = _text(at)
    saved = len(list((UI / "fixtures" / "runs").glob("*.json")))
    assert f"Judge mode: {saved} invoices, 1 funded" in text
    assert "Stopped: duplicate invoice (saved demo)" in text
    at.button(key="show_happy").click().run()
    assert not at.exception and "Funded inside the rules" in _text(at)


def test_judge_mode_after_a_live_happy_run_reuses_it_instead_of_posting_it_again(monkeypatch):
    import client as orch

    sent = []

    def fake_run_flow(self, content, filename, mandate_id="mdt_001"):
        sent.append(filename)
        case = filename.split("_", 1)[1].removesuffix(".pdf")
        return json.loads((UI / "fixtures" / "runs" / f"{case}.json").read_text(encoding="utf-8"))

    monkeypatch.setenv("UI_MODE", "live")
    monkeypatch.setattr(orch.Orchestrator, "run_flow", fake_run_flow)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.button(key="case_happy").click().run()
    at.button(key="run_all").click().run()
    assert not at.exception
    assert sent == ["01_happy.pdf", "02_injected.pdf", "03_inflated.pdf", "04_duplicate.pdf"]
    assert "Judge mode: 4 invoices, 1 funded" in _text(at)
