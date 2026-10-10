"""Orchestrator-only client and view-model adapter for the demo screen (UI_MODE=live).

The UI never calls ocr-ai, policy-ai or agent-wallet directly. Every call goes to ORCHESTRATOR_URL
(default http://localhost:8000). Routes the orchestrator doesn't serve yet raise `Unsupported`, and the screen
falls back to the saved fixture for that part with a visible label. A connection error raises `Unavailable`.

`to_view` maps both orchestrator shapes onto the one view model the screen draws:
- today's flat dict: {mandate_id, ocr, registry, policy, wallet, outcome}
- the brief's shape: {flow_id, state, steps: [{name, ...result}]}
Parts the response doesn't carry (mandate, offers, ledger timeline) come from the fixture and are listed in
view["from_fixture"], so the screen can label them.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

TIMEOUT_SECONDS = 60
STEP_KEYS = {
    "ocr": ("ocr", "extract", "ocr_extract"),
    "registry": ("registry", "register", "duplicate_check"),
    "policy": ("policy", "decide", "policy_decide"),
    "offers": ("offers", "quotes", "lender_quotes"),
    "wallet": ("wallet", "execute", "wallet_execute"),
    "mandate": ("mandate", "mandate_compile"),
}


class Unavailable(Exception):
    """The orchestrator could not be reached or answered with a server error."""


class Unsupported(Exception):
    """The orchestrator has no route for this action yet (404 / 405)."""


def base_url() -> str:
    return os.getenv("ORCHESTRATOR_URL", "http://localhost:8000").rstrip("/")


class Orchestrator:
    def __init__(self, url: str | None = None, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(base_url=url or base_url(), timeout=TIMEOUT_SECONDS, transport=transport)

    def _call(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            r = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise Unavailable(f"{type(exc).__name__} calling {path}") from exc
        if r.status_code in (404, 405):
            raise Unsupported(path)
        if r.status_code >= 500:
            raise Unavailable(f"HTTP {r.status_code} from {path}")
        r.raise_for_status()
        return r.json()

    def health(self) -> bool:
        try:
            return self._call("GET", "/health").get("status") == "ok"
        except (Unavailable, Unsupported, httpx.HTTPStatusError):
            return False

    def run_flow(self, content: bytes, filename: str, mandate_id: str = "mdt_001") -> dict:
        return self._call(
            "POST", "/flow/run", files={"file": (filename, content)}, data={"mandate_id": mandate_id}
        )

    def repay(self, view: dict) -> dict:
        if view.get("flow_id"):
            body = {"flow_id": view["flow_id"], "amount_paid": view["ocr"]["amount"]}
            return self._call("POST", "/flow/repay", json=body)
        return self._call("POST", "/flow/repay", data={"invoice_id": view["ocr"]["invoice_id"]})

    def attack(self, case: str) -> dict:
        return self._call("POST", f"/flow/attack/{case.upper()}")

    def compile_mandate(self, text: str) -> dict:
        return self._call("POST", "/flow/mandate/compile", json={"text": text})

    def confirm(self, tx_id: str) -> dict:
        return self._call("POST", f"/flow/confirm/{tx_id}")


def _steps(raw: dict) -> dict[str, Any]:
    """{part: payload} from either response shape."""
    if isinstance(raw.get("steps"), list):
        out = {}
        for step in raw["steps"]:
            name = str(step.get("name") or step.get("step") or "").lower()
            payload = step.get("result", step.get("output", step))
            for part, names in STEP_KEYS.items():
                if name in names:
                    out[part] = payload
        return out
    return {part: raw[names[0]] for part, names in STEP_KEYS.items() if names[0] in raw}


def wallet_tx(wallet: dict) -> dict:
    """One timeline row from a WalletResult."""
    return {
        "step": "TX-4",
        "call": "wallet execute",
        "tx_id": wallet.get("tx_id"),
        "status": wallet.get("status", "unknown"),
        "chain_ref": wallet.get("chain_ref") or wallet.get("tx_id"),
        "chain": wallet.get("chain"),
        "block_reason": wallet.get("block_reason"),
    }


def to_view(raw: dict, fixture: dict) -> dict:
    """The screen's view model from an orchestrator response, with fixture parts labelled."""
    parts = _steps(raw)
    view: dict[str, Any] = {
        "source": "orchestrator",
        "flow_id": raw.get("flow_id"),
        "state": raw.get("state") or raw.get("outcome"),
        "mandate_text": fixture["mandate_text"],
        "from_fixture": [],
    }
    if "ocr" not in parts:
        raise ValueError("orchestrator response has no ocr step")
    view["ocr"] = parts["ocr"]
    view["policy"] = parts.get("policy")  # None when the flow stopped before policy (e.g. a duplicate)
    view["registry"] = parts.get("registry", {})
    for part in ("mandate", "offers"):
        if part in parts:
            view[part] = parts[part]
        else:
            view[part] = fixture[part]
            view["from_fixture"].append(part)
    wallet = parts.get("wallet")
    if wallet:
        view["wallet"] = wallet
        view["timeline"] = [wallet_tx(wallet)]
    else:  # stopped before the wallet (duplicate, reject, review)
        view["wallet"] = {"status": view["state"], "chain": None, "audit_ref": "-"}
        view["timeline"] = []
    if view["registry"].get("duplicate"):
        view["timeline"].insert(
            0,
            {
                "step": "TX-1",
                "call": "registry duplicate check",
                "status": "blocked",
                "chain_ref": None,
                "block_reason": "DuplicateReceivable",
            },
        )
    view["repay"] = None
    return view


def action_row(resp: dict, step: str, call: str) -> dict:
    """Timeline row for an [Approve] or [Buyer paid] response, whatever its shape."""
    status = str(resp.get("status", "unknown"))
    known = status in ("executed", "blocked", "failed", "pending_approval", "settled")
    return {
        "step": step,
        "call": call,
        "status": status if known else "unknown",
        "chain_ref": resp.get("chain_ref") or resp.get("tx_id"),
        "block_reason": resp.get("block_reason") or (None if known else status),
    }


def attack_row(resp: dict, saved: dict) -> dict:
    """A red row from a live /flow/attack response; text the response lacks comes from the saved case."""
    policy = resp.get("policy") or {}
    wallet = resp.get("wallet") or {}
    reasons = policy.get("reasons", [])
    return {
        **saved,
        "label": "live",
        "stopped_by": resp.get("stopped_by", saved["stopped_by"]),
        "policy_decision": policy.get("decision", saved.get("policy_decision")),
        "policy_reasons": [r.split(":", 1)[0] for r in reasons if not r.startswith("MODEL.")]
        or saved.get("policy_reasons", []),
        "status": wallet.get("status") or resp.get("status") or resp.get("outcome") or "unknown",
        "block_reason": wallet.get("block_reason") or resp.get("block_reason"),
        "chain_ref": wallet.get("chain_ref") or resp.get("chain_ref"),
    }
