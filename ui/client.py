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

import json
import os
import re
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


class ServiceError(Unavailable):
    """The orchestrator answered, but one of the services behind it failed; `plain` says which, in words."""

    def __init__(self, message: str, plain: str):
        super().__init__(message)
        self.plain = plain


class Unsupported(Exception):
    """The orchestrator has no route for this action yet (404 / 405)."""


class Refused(Exception):
    """policy-ai would not compile the sentence. `violations` are its rows: {field, code, value, limit}."""

    def __init__(self, violations: list[dict]):
        super().__init__("mandate refused")
        self.violations = violations

    @property
    def plain(self) -> str:
        """'Refused: max_ltv OUT_OF_RANGE (asked 0.95, limit 0.90)', one clause per violated limit."""
        return "Refused: " + ("; ".join(map(_describe, self.violations)) or "the sentence was not accepted")


def _describe(v: dict) -> str:
    field = v.get("field") or (v.get("loc") or ["text"])[-1]  # policy-ai's row, or a request-validation row
    text = f"{field} {v.get('code') or v.get('type') or 'invalid'}"
    facts = [f"asked {v['value']}" if v.get("value") else "", f"limit {v['limit']}" if v.get("limit") else ""]
    facts = [fact for fact in facts if fact]
    return text + (f" ({', '.join(facts)})" if facts else "")


def base_url() -> str:
    return os.getenv("ORCHESTRATOR_URL", "http://localhost:8000").rstrip("/")


def auth_headers() -> dict[str, str]:
    """The orchestrator's caller token (ORCHESTRATOR_TOKEN in .env), sent on every call; none when unset."""
    token = os.getenv("ORCHESTRATOR_TOKEN", "").strip()
    return {"X-Orchestrator-Token": token} if token else {}


class Orchestrator:
    def __init__(self, url: str | None = None, transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(
            base_url=url or base_url(), timeout=TIMEOUT_SECONDS, transport=transport, headers=auth_headers()
        )

    def _call(self, method: str, path: str, refusal: bool = False, **kwargs: Any) -> dict:
        try:
            r = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise Unavailable(f"{type(exc).__name__} calling {path}") from exc
        if r.status_code in (404, 405):
            raise Unsupported(path)
        if refusal and r.status_code == 422:
            raise _Refusal(_violations(r))
        if r.status_code >= 500:
            detail = _detail(r)
            if detail:
                raise ServiceError(f"HTTP {r.status_code} from {path}: {detail}", plain_error(detail))
            raise Unavailable(f"HTTP {r.status_code} from {path}")
        if r.status_code in (401, 403):
            plain = "the orchestrator refused the screen: set ORCHESTRATOR_TOKEN to the orchestrator's token"
            raise ServiceError(f"HTTP {r.status_code} from {path}: {_detail(r)}", plain)
        if (
            r.status_code >= 400
        ):  # e.g. 415 when OCR refuses the uploaded file: the file's fault, said plainly
            detail = _detail(r) or f"HTTP {r.status_code}"
            raise ServiceError(f"HTTP {r.status_code} from {path}: {detail}", plain_error(detail))
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
        """The sentence as a mandate envelope. A sentence policy-ai refuses (422) raises Refused."""
        try:
            return self._call("POST", "/flow/mandate/compile", json={"text": text}, refusal=True)
        except _Refusal as exc:
            raise Refused(exc.violations) from None

    def confirm(self, tx_id: str) -> dict:
        return self._call("POST", f"/flow/confirm/{tx_id}")


class _Refusal(Exception):
    def __init__(self, violations: list[dict]):
        self.violations = violations


def _violations(r: httpx.Response) -> list[dict]:
    try:
        detail = r.json().get("detail")
    except ValueError:
        return []
    if isinstance(detail, list):
        return [v for v in detail if isinstance(v, dict)]
    return [{"field": "text", "code": detail}] if isinstance(detail, str) else []


SERVICE_NAMES = {"/ocr/": "the OCR service", "/policy/": "the policy service", "/wallet/": "the agent wallet"}


def _detail(r: httpx.Response) -> str:
    try:
        detail = r.json().get("detail")
    except ValueError:
        return ""
    return detail if isinstance(detail, str) else ""


def plain_error(detail: str) -> str:
    """'http://x:8001/ocr/extract answered 415: {"detail": "..."}' -> 'the OCR service refused the request
    (HTTP 415): ...', so a judge sees which step failed and why instead of a bare 502."""
    service = next((name for key, name in SERVICE_NAMES.items() if key in detail), "a service")
    match = re.search(r"answered (\d{3}): ?(.*)", detail, re.S)
    if not match:
        return f"{service} failed: {detail[:200]}"
    code, reason = match.groups()
    try:
        inner = json.loads(reason).get("detail")
        reason = inner if isinstance(inner, str) else reason
    except (ValueError, AttributeError):
        pass  # the service's body was cut at 300 characters or isn't JSON; show it as text
    verb = "refused the request" if code.startswith("4") else "failed"
    return f"{service} {verb} (HTTP {code}): {reason[:200]}"


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


TX_CALLS = {
    "TX-1": "Registry.register (duplicate check)",
    "TX-2": "Registry.approve (credit approval)",
    "TX-4": "AgentWallet.execute -> Vault.draw",
}


def wallet_tx(wallet: dict, step: str = "TX-4") -> dict:
    """One timeline row from a WalletResult."""
    return {
        "step": step,
        "call": TX_CALLS.get(step, "wallet execute"),
        "tx_id": wallet.get("tx_id"),
        "status": wallet.get("status", "unknown"),
        "chain_ref": wallet.get("chain_ref") or wallet.get("tx_id"),
        "chain": wallet.get("chain"),
        "block_reason": wallet.get("block_reason"),
    }


def offer_reason(offer: dict) -> str:
    if offer.get("chosen"):
        return "highest advance within the approved APR"
    if not offer.get("within_mandate", True):
        return "APR above the approved rate"
    return "lower advance"


def to_view(raw: dict, fixture: dict) -> dict:
    """The screen's view model from an orchestrator response, with fixture parts labelled.

    A part the flow never reached (offers after a review, the wallet after a duplicate) stays empty and is
    listed in view["not_reached"]; only a part an older orchestrator doesn't return falls back to the fixture.
    """
    parts = _steps(raw)
    view: dict[str, Any] = {
        "source": "orchestrator",
        "flow_id": raw.get("flow_id"),
        "state": raw.get("state") or raw.get("outcome"),
        "mandate_text": fixture["mandate_text"],
        "from_fixture": [],
        "not_reached": [],
    }
    if "ocr" not in parts:
        raise ValueError("orchestrator response has no ocr step")
    view["ocr"] = parts["ocr"]
    view["policy"] = parts.get("policy")  # None when the flow stopped before policy (e.g. a duplicate)
    view["registry"] = parts.get("registry", {})
    wallet = parts.get("wallet")
    if "mandate" in parts:
        view["mandate"] = parts["mandate"]
    else:
        view["mandate"] = fixture["mandate"]
        view["from_fixture"].append("mandate")
    if "offers" in parts:
        view["offers"] = [{**o, "reason": o.get("reason") or offer_reason(o)} for o in parts["offers"]]
    elif wallet:  # the draw ran, so quotes existed: this orchestrator just doesn't return them
        view["offers"] = fixture["offers"]
        view["from_fixture"].append("offers")
    else:
        view["offers"] = []
        view["not_reached"].append("offers")
    register, approve = raw.get("register"), raw.get("approve")
    view["timeline"] = [wallet_tx(r, step) for r, step in ((register, "TX-1"), (approve, "TX-2")) if r]
    if wallet:
        view["wallet"] = wallet
        view["timeline"].append(wallet_tx(wallet))
    else:  # stopped before the wallet (duplicate, reject, review)
        chain = (register or {}).get("chain")
        view["wallet"] = {
            "status": view["state"],
            "chain": chain,
            "audit_ref": (register or {}).get("audit_ref"),
        }
        view["not_reached"].append("wallet")
    if view["registry"].get("duplicate") and not register:
        view["timeline"].insert(
            0,
            {
                "step": "TX-1",
                "call": TX_CALLS["TX-1"],
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
        # Policy ran only if the response carries it (A2 stops at the registry); never the saved row's.
        "policy_decision": policy.get("decision"),
        "policy_reasons": [r.split(":", 1)[0] for r in reasons if not r.startswith("MODEL.")],
        "status": wallet.get("status") or resp.get("status") or resp.get("outcome") or "unknown",
        "block_reason": wallet.get("block_reason") or resp.get("block_reason"),
        "chain_ref": wallet.get("chain_ref") or resp.get("chain_ref"),
    }
