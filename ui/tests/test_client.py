"""The orchestrator client and the view-model adapter (ui/client.py), on mocked HTTP only."""

import json
from pathlib import Path

import client as orch
import httpx
import pytest

FIXTURE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "happy.json").read_text("utf-8"))


def _stub_response(wallet_status="pending_approval", duplicate=False) -> dict:
    """The orchestrator's current flat shape (services/orchestrator/app/main.py)."""
    raw = {
        "mandate_id": "mdt_001",
        "ocr": FIXTURE["ocr"],
        "registry": {"invoice_fingerprint": FIXTURE["ocr"]["invoice_fingerprint"], "duplicate": duplicate},
    }
    if duplicate:
        return {**raw, "outcome": "blocked: invoice already registered"}
    wallet = {
        "tx_id": "stub-abc",
        "status": wallet_status,
        "chain_ref": None,
        "approvals_required": 1,
        "audit_ref": "audit-inv",
    }
    return {**raw, "policy": FIXTURE["policy"], "wallet": wallet, "outcome": wallet_status}


def _client(handler) -> orch.Orchestrator:
    return orch.Orchestrator("http://orch.test", transport=httpx.MockTransport(handler))


def test_flat_stub_shape_maps_to_the_view_and_labels_fixture_parts():
    view = orch.to_view(_stub_response(), FIXTURE)
    assert view["source"] == "orchestrator" and view["state"] == "pending_approval"
    assert view["policy"] == FIXTURE["policy"] and view["ocr"] == FIXTURE["ocr"]
    assert view["from_fixture"] == ["mandate", "offers"]
    assert (
        view["timeline"][0]["status"] == "pending_approval" and view["timeline"][0]["chain_ref"] == "stub-abc"
    )
    assert view["repay"] is None


def test_steps_shape_maps_to_the_same_view():
    raw = {
        "flow_id": "flow_1",
        "state": "FUNDED",
        "steps": [
            {"name": "ocr", "result": FIXTURE["ocr"]},
            {"name": "policy", "result": FIXTURE["policy"]},
            {"name": "quotes", "result": FIXTURE["offers"]},
            {"name": "wallet", "result": FIXTURE["wallet"]},
        ],
    }
    view = orch.to_view(raw, FIXTURE)
    assert view["flow_id"] == "flow_1" and view["state"] == "FUNDED"
    assert view["offers"] == FIXTURE["offers"] and view["from_fixture"] == ["mandate"]
    assert view["timeline"][0]["status"] == "executed"


def test_a_duplicate_stops_before_the_wallet_with_a_red_registry_row():
    view = orch.to_view(_stub_response(duplicate=True), FIXTURE)  # stops at the registry, before policy
    assert view["policy"] is None
    assert view["timeline"][0]["block_reason"] == "DuplicateReceivable"
    assert view["wallet"]["status"].startswith("blocked")


def test_a_response_without_an_ocr_step_is_rejected():
    with pytest.raises(ValueError):
        orch.to_view({"policy": FIXTURE["policy"]}, FIXTURE)


def test_missing_routes_raise_unsupported_and_errors_raise_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/flow/attack"):
            return httpx.Response(404, json={"detail": "Not Found"})
        if request.url.path == "/flow/mandate/compile":
            return httpx.Response(405)
        return httpx.Response(502)

    c = _client(handler)
    with pytest.raises(orch.Unsupported):
        c.attack("a3")
    with pytest.raises(orch.Unsupported):
        c.compile_mandate("never pay more than 12% APR")
    with pytest.raises(orch.Unavailable):
        c.run_flow(b"x", "invoice.txt")
    assert c.health() is False


def test_connection_refused_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(orch.Unavailable):
        _client(handler).run_flow(b"x", "invoice.txt")


def test_run_flow_posts_the_file_and_mandate_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["body"] = request.url.path, request.content
        return httpx.Response(200, json=_stub_response())

    raw = _client(handler).run_flow(b"invoice bytes", "demo_invoice.txt")
    assert seen["path"] == "/flow/run" and b"invoice bytes" in seen["body"] and b"mdt_001" in seen["body"]
    assert raw["outcome"] == "pending_approval"


def test_repay_uses_json_with_a_flow_id_and_the_form_otherwise():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.headers["content-type"], request.content))
        return httpx.Response(200, json={"invoice_id": "x", "status": "stub: settlement not implemented yet"})

    c = _client(handler)
    resp = c.repay({"ocr": FIXTURE["ocr"]})
    c.repay({"flow_id": "flow_1", "ocr": FIXTURE["ocr"]})
    assert seen[0][0].startswith("application/x-www-form-urlencoded") and b"invoice_id=" in seen[0][1]
    assert seen[1][0] == "application/json" and json.loads(seen[1][1])["amount_paid"] == "749000.00"
    row = orch.action_row(resp, "TX-5", "Buyer paid")
    assert row["status"] == "unknown" and row["block_reason"].startswith("stub")


def test_attack_row_reports_what_the_orchestrator_returned():
    saved = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "a3.json").read_text("utf-8"))
    live = orch.attack_row(
        {"wallet": {"status": "blocked", "block_reason": "AprAboveMandate", "chain_ref": "mock:0x01"}}, saved
    )
    assert live["status"] == "blocked" and live["chain_ref"] == "mock:0x01" and live["label"] == "live"
    leaked = orch.attack_row({"status": "executed"}, saved)
    assert leaked["status"] == "executed"  # never relabelled as blocked


def _tx(status="executed", block_reason=None) -> dict:
    return {
        "tx_id": "tx_1",
        "status": status,
        "chain_ref": "mock:0x01",
        "chain": "mock",
        "block_reason": block_reason,
    }


def test_todays_orchestrator_fills_the_whole_timeline_and_the_offers():
    offers = [
        {
            "lender": "Andaman",
            "advance_rate": "0.70",
            "apr": "0.1095",
            "within_mandate": True,
            "chosen": True,
        },
        {"lender": "Isan", "advance_rate": "0.75", "apr": "0.15", "within_mandate": False, "chosen": False},
    ]
    raw = {**_stub_response("executed"), "register": _tx(), "approve": _tx(), "offers": offers}
    view = orch.to_view(raw, FIXTURE)
    assert [t["step"] for t in view["timeline"]] == ["TX-1", "TX-2", "TX-4"]
    assert view["from_fixture"] == ["mandate"] and view["not_reached"] == []
    assert [o["reason"] for o in view["offers"]] == [
        "highest advance within the approved APR",
        "APR above the approved rate",
    ]


def test_a_review_shows_the_register_tx_and_marks_offers_and_wallet_not_reached():
    raw = {
        "mandate_id": "mdt_001",
        "ocr": FIXTURE["ocr"],
        "register": _tx(),
        "registry": {"duplicate": False},
        "policy": {**FIXTURE["policy"], "decision": "review"},
        "outcome": "review: wallet not called",
    }
    view = orch.to_view(raw, FIXTURE)
    assert view["offers"] == [] and view["not_reached"] == ["offers", "wallet"]
    assert [t["step"] for t in view["timeline"]] == ["TX-1"]
    assert view["wallet"]["chain"] == "mock"  # the ledger badge still says which ledger the TX-1 went to


def test_a_live_duplicate_keeps_the_wallets_own_block_row():
    raw = {
        "ocr": FIXTURE["ocr"],
        "register": _tx("blocked", "DuplicateReceivable"),
        "registry": {"duplicate": True},
        "outcome": "blocked: DuplicateReceivable",
    }
    view = orch.to_view(raw, FIXTURE)
    assert len(view["timeline"]) == 1 and view["timeline"][0]["block_reason"] == "DuplicateReceivable"


def test_a_failing_service_is_named_in_plain_words():
    detail = 'http://localhost:8001/ocr/extract answered 415: {"detail":"unsupported file type"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"detail": detail})

    with pytest.raises(orch.ServiceError) as err:
        _client(handler).run_flow(b"x", "invoice.txt")
    assert err.value.plain == "the OCR service refused the request (HTTP 415): unsupported file type"
    assert orch.plain_error("http://w:8003/wallet/execute answered 500: boom").startswith(
        "the agent wallet failed"
    )


def test_a_refused_upload_is_a_plain_error_not_a_crash():
    detail = 'http://localhost:8001/ocr/extract answered 415: {"detail":"Only PDF, JPEG, and PNG uploads"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(415, json={"detail": detail})

    with pytest.raises(orch.ServiceError) as err:
        _client(handler).run_flow(b"x", "notes.txt")
    assert (
        err.value.plain == "the OCR service refused the request (HTTP 415): Only PDF, JPEG, and PNG uploads"
    )


def test_the_orchestrator_token_rides_every_call(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("X-Orchestrator-Token"))
        return httpx.Response(200, json=_stub_response())

    monkeypatch.setenv("ORCHESTRATOR_TOKEN", "t0ken")
    _client(handler).run_flow(b"%PDF", "invoice.pdf")
    monkeypatch.delenv("ORCHESTRATOR_TOKEN")
    _client(handler).run_flow(b"%PDF", "invoice.pdf")
    assert seen == ["t0ken", None]


def test_a_missing_token_is_said_plainly():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "Unauthorized"})

    with pytest.raises(orch.ServiceError) as err:
        _client(handler).run_flow(b"%PDF", "invoice.pdf")
    assert "set ORCHESTRATOR_TOKEN" in err.value.plain
