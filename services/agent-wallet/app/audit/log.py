"""Hash-chained audit log (CLAUDE.md 5.8). Owner: Agent AI engineer.

Every wallet action leaves entries, whether it executed or was blocked. Each entry commits to the one before
it, so editing, reordering or dropping an entry makes verify() fail. The head is anchored on chain after
each settlement (ledger.anchor_audit). Entries hold ids, hashes, amounts and codes only, never invoice text.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

GENESIS = "0x" + "00" * 32


def _digest(prev_hash: str, body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return "0x" + hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    @property
    def head(self) -> str:
        return self.entries[-1]["hash"] if self.entries else GENESIS

    def record(
        self,
        *,
        invoice_id: str,
        audit_ref: str,
        action: str,
        event: str,
        actor: str,
        tx_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = {
            "seq": len(self.entries) + 1,
            "ts": datetime.now(UTC).isoformat(),
            "invoice_id": invoice_id,
            "audit_ref": audit_ref,
            "tx_id": tx_id,
            "action": action,
            "event": event,
            "actor": actor,
            "data": data or {},
            "prev_hash": self.head,
        }
        entry = {**body, "hash": _digest(self.head, body)}
        self.entries.append(entry)
        return entry

    def verify(self, entries: list[dict[str, Any]] | None = None) -> bool:
        """Recomputes every hash and link. Any edit, reorder or deletion makes this False."""
        prev = GENESIS
        for index, entry in enumerate(self.entries if entries is None else entries, start=1):
            body = {k: v for k, v in entry.items() if k != "hash"}
            if entry.get("seq") != index or entry.get("prev_hash") != prev:
                return False
            if _digest(prev, body) != entry.get("hash"):
                return False
            prev = entry["hash"]
        return True

    def for_invoice(self, invoice_id: str) -> list[dict[str, Any]]:
        return [e for e in self.entries if e["invoice_id"] == invoice_id]

    def for_ref(self, audit_ref: str) -> list[dict[str, Any]]:
        return [e for e in self.entries if e["audit_ref"] == audit_ref]
