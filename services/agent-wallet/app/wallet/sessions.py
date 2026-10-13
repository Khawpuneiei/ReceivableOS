"""Scoped session keys for the agent (ERC-7715 / ERC-4337 session-key style, off-chain).

Owner: Agent AI engineer.

The static agent token is one long-lived credential with the agent's full power. A session key narrows it:
the owner grants the agent a short-lived token for named actions, a spending budget, a per-draw cap and,
optionally, a closed list of invoice fingerprints (an intent-bound grant, like AP2's intent mandate).
A stolen session token is worth at most its remaining budget until it expires, and the owner or the approver
can revoke it at once.

Every session is bound to the mandate hash it was issued under, so a new mandate voids older sessions. Only
a SHA-256 of the token is stored; the token itself is returned once, at issue. Session checks run before the
wallet's guard (layer "SK"); the guard and the chain still run in full after them.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models import PositiveMoney

Action = Literal["register", "execute", "settle"]
MAX_TTL_MINUTES = 24 * 60


class SessionGrant(BaseModel):
    """Body of POST /wallet/session (owner token)."""

    label: str = Field(default="agent", max_length=64)
    actions: list[Action] = Field(min_length=1)
    budget: PositiveMoney  # total THB the session may draw, pending draws included
    max_per_tx: PositiveMoney
    ttl_minutes: int = Field(default=60, ge=1, le=MAX_TTL_MINUTES)
    invoice_fingerprints: list[str] | None = None  # None: any invoice; a list: only these

    @field_validator("invoice_fingerprints")
    @classmethod
    def _lower(cls, v: list[str] | None) -> list[str] | None:
        return [fp.lower() for fp in v] if v is not None else None


@dataclass
class Session:
    session_id: str
    token_sha256: str
    grant: SessionGrant
    mandate_hash: str
    issued_at: datetime
    expires_at: datetime
    spent: Decimal = Decimal(0)
    revoked: bool = False
    uses: list[str] = field(default_factory=list)  # tx ids done under this session

    def view(self) -> dict:
        return {
            "session_id": self.session_id,
            "label": self.grant.label,
            "actions": self.grant.actions,
            "budget": str(self.grant.budget),
            "spent": str(self.spent),
            "max_per_tx": str(self.grant.max_per_tx),
            "invoice_fingerprints": self.grant.invoice_fingerprints,
            "mandate_hash": self.mandate_hash,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "revoked": self.revoked,
            "uses": len(self.uses),
        }


def _sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}  # session_id -> session

    def issue(self, grant: SessionGrant, mandate_hash: str, now: datetime) -> tuple[Session, str]:
        if grant.max_per_tx > grant.budget:
            raise ValueError("max_per_tx is above the session budget")
        token = "sk_" + secrets.token_urlsafe(32)
        session = Session(
            session_id=f"ses_{uuid.uuid4().hex[:12]}",
            token_sha256=_sha256(token),
            grant=grant,
            mandate_hash=mandate_hash.lower(),
            issued_at=now,
            expires_at=now + timedelta(minutes=grant.ttl_minutes),
        )
        self.sessions[session.session_id] = session
        return session, token

    def find(self, token: str | None) -> Session | None:
        if not token:
            return None
        digest = _sha256(token)
        return next(
            (s for s in self.sessions.values() if secrets.compare_digest(s.token_sha256, digest)), None
        )

    def check(
        self,
        session: Session,
        action: Action,
        now: datetime,
        mandate_hash: str | None,
        fingerprint: str | None = None,
        amount: Decimal | None = None,
    ) -> str | None:
        """The first failing scope rule as a reason code, or None when the call is inside the grant."""
        if session.revoked:
            return "SessionRevoked"
        if now >= session.expires_at:
            return "SessionExpired"
        if (mandate_hash or "").lower() != session.mandate_hash:
            return "SessionMandateChanged"
        if action not in session.grant.actions:
            return "SessionActionNotAllowed"
        allowed = session.grant.invoice_fingerprints
        if allowed is not None and (fingerprint or "").lower() not in allowed:
            return "SessionInvoiceNotAllowed"
        if amount is not None and amount > session.grant.max_per_tx:
            return "SessionTxCapExceeded"
        if amount is not None and session.spent + amount > session.grant.budget:
            return "SessionBudgetExceeded"
        return None

    def revoke(self, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        if session is None:
            return False
        session.revoked = True
        return True
