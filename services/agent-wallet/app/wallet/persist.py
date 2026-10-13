"""Durable wallet state (CLAUDE.md 5.5). Owner: Agent AI engineer.

The store and the audit log live in memory. Without this, a restart loses the held drafts, the ids of the
draws waiting for an approver, the idempotency results and the audit trail, while the chain keeps its side.
StateFile writes one JSON snapshot after every audited action and reads it back at startup.

The snapshot is tied to the deployed AgentWallet address: state written for one deployment is never loaded
onto another. It holds ids, hashes, amounts, codes and the stored requests. It holds no keys and no tokens.
The 24h spend is not saved, because startup reads it from the chain (PolicyGuard.rollingSpend).

A crash between a ledger call and the save loses that one result. The chain still refuses a repeat (already
drawn, already settled, duplicate receivable), so the worst case is a blocked retry, never a second payment.
"""

import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.audit.log import AuditLog
from app.models import DrawIntent, ExecuteRequest
from app.wallet.store import Hold, ReceivableFact, Store
from shared.schemas import GuardCheck, WalletResult

VERSION = 1


def _fact_out(fact: ReceivableFact) -> dict[str, Any]:
    return {
        "invoice_id": fact.invoice_id,
        "seller_id": fact.seller_id,
        "seller_address": fact.seller_address,
        "face_value": str(fact.face_value),
        "due_date": fact.due_date.isoformat(),
        "fee_rate": None if fact.fee_rate is None else str(fact.fee_rate),
        "limit": None if fact.limit is None else str(fact.limit),
        "decision_hash": fact.decision_hash,
        "drawn_amount": None if fact.drawn_amount is None else str(fact.drawn_amount),
    }


def _fact_in(raw: dict[str, Any]) -> ReceivableFact:
    def money(value: str | None) -> Decimal | None:
        return None if value is None else Decimal(value)

    return ReceivableFact(
        invoice_id=raw["invoice_id"],
        seller_id=raw["seller_id"],
        seller_address=raw["seller_address"],
        face_value=Decimal(raw["face_value"]),
        due_date=date.fromisoformat(raw["due_date"]),
        fee_rate=money(raw["fee_rate"]),
        limit=money(raw["limit"]),
        decision_hash=raw["decision_hash"],
        drawn_amount=money(raw["drawn_amount"]),
    )


def _hold_out(hold: Hold) -> dict[str, Any]:
    return {
        "tx_id": hold.tx_id,
        "intent": hold.intent.model_dump(mode="json"),
        "request": hold.request.model_dump(mode="json"),
        "checks": [c.model_dump(mode="json") for c in hold.checks],
        "held_at": hold.held_at.isoformat(),
    }


def _hold_in(raw: dict[str, Any]) -> Hold:
    return Hold(
        tx_id=raw["tx_id"],
        intent=DrawIntent.model_validate(raw["intent"]),
        request=ExecuteRequest.model_validate(raw["request"]),
        checks=[GuardCheck.model_validate(c) for c in raw["checks"]],
        held_at=datetime.fromisoformat(raw["held_at"]),
    )


class StateFile:
    def __init__(self, path: str | Path, deployment: str) -> None:
        self.path = Path(path)
        self.deployment = deployment.lower()  # the AgentWallet address this state belongs to

    def save(self, store: Store, audit: AuditLog, paused: bool) -> None:
        data = {
            "version": VERSION,
            "deployment": self.deployment,
            "paused": paused,
            "results": {key: r.model_dump(mode="json") for key, r in store.results.items()},
            "receivables": {fp: _fact_out(f) for fp, f in store.receivables.items()},
            "pending": store.pending,
            "txs": {tx: [invoice, r.model_dump(mode="json")] for tx, (invoice, r) in store.txs.items()},
            "holds": {tx: _hold_out(h) for tx, h in store.holds.items()},
            "audit": audit.entries,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temporary, self.path)  # atomic: a crash leaves the old snapshot or the new one, never half

    def load_into(self, store: Store, audit: AuditLog) -> bool | None:
        """Restores the snapshot. Returns the saved pause flag, or None when there is nothing to restore:
        no file yet, or a file written for another deployment. A snapshot that fails its own audit check, or
        that this code cannot read, raises: the wallet must not start on state it cannot trust."""
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("deployment") != self.deployment:
            return None
        if data.get("version") != VERSION:
            raise RuntimeError(f"wallet state file {self.path} has version {data.get('version')}")
        if not audit.verify(data["audit"]):
            raise RuntimeError(f"wallet state file {self.path} fails its audit hash check")
        store.results = {key: WalletResult.model_validate(r) for key, r in data["results"].items()}
        store.receivables = {fp: _fact_in(f) for fp, f in data["receivables"].items()}
        store.pending = {tx: int(pending) for tx, pending in data["pending"].items()}
        store.txs = {tx: (pair[0], WalletResult.model_validate(pair[1])) for tx, pair in data["txs"].items()}
        store.holds = {tx: _hold_in(h) for tx, h in data["holds"].items()}
        audit.entries = data["audit"]
        return bool(data["paused"])
