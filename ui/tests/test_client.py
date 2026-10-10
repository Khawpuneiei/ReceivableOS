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
