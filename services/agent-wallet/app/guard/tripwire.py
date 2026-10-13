"""Tripwire: honeytokens, invoice quarantine and an attack circuit breaker. Owner: Agent AI engineer.

Detectors miss things, and attackers iterate: the variant the scanner misses usually follows one it caught.
The tripwire turns each caught attack into state, so the next attempt meets a closed door:

- Honeytokens: decoy payee ids and addresses that no legitimate flow uses (config/tripwire.json). A request
  carrying one anywhere, in a field or in free text, proves forged instructions or leaked context. It is
  blocked and the wallet pauses at once, on chain too.
- Quarantine: an invoice fingerprint that drew a hostile block (injection, canary, tampered decision, payee
  swap) is quarantined. Later writes on it are blocked as InvoiceQuarantined until an approver releases it, so
  a second, better-obfuscated attempt on the same invoice cannot slip past the scanner. Settlement is exempt.
- Circuit breaker: `threshold` hostile blocks within `window_minutes` pause the whole wallet. Only the owner
  can unpause, as for a manual pause, and unpausing re-arms the breaker.

Policy refusals (APR, limit, caps) are not hostile signals: an honest mistake must not freeze the wallet.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.guard.injection import iter_strings

HOSTILE = {
    "InjectionSuspected",
    "CanaryLeak",
    "DecisionTampered",
    "PayeeNotAllowed",
    "MandateMismatch",
    "HoneytokenTouched",
}


@dataclass
class Tripwire:
    honeytokens: set[str]
    threshold: int = 3  # 0 turns the breaker off; honeytokens and quarantine stay on
    window: timedelta = timedelta(minutes=10)
    signals: list[tuple[datetime, str, str]] = field(default_factory=list)  # (when, code, fingerprint)
    quarantined: dict[str, str] = field(default_factory=dict)  # fingerprint -> first hostile code
    tripped_at: datetime | None = None

    @classmethod
    def load(cls, path: Path) -> "Tripwire":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            honeytokens={str(t).lower() for t in raw.get("honeytokens", [])},
            threshold=int(raw.get("threshold", 3)),
            window=timedelta(minutes=int(raw.get("window_minutes", 10))),
        )

    def honeytoken_in(self, payload: Any) -> str | None:
        """The json path of the first honeytoken found in any string of the payload, or None."""
        for path, value in iter_strings(payload):
            low = value.lower()
            if any(token in low for token in self.honeytokens):
                return path
        return None

    def observe(self, now: datetime, fingerprint: str, codes: set[str]) -> bool:
        """Records the hostile codes of one blocked result. True when this result trips the breaker."""
        hostile = sorted(codes & HOSTILE)
        if not hostile:
            return False
        if fingerprint:
            self.quarantined.setdefault(fingerprint.lower(), hostile[0])
        self.signals.append((now, hostile[0], fingerprint))
        if "HoneytokenTouched" in hostile:
            return self._trip(now)
        recent = [s for s in self.signals if s[0] >= now - self.window]
        return self.threshold > 0 and len(recent) >= self.threshold and self._trip(now)

    def _trip(self, now: datetime) -> bool:
        first = self.tripped_at is None
        self.tripped_at = now
        return first

    def is_quarantined(self, fingerprint: str | None) -> bool:
        return bool(fingerprint) and fingerprint.lower() in self.quarantined

    def release(self, fingerprint: str) -> bool:
        return self.quarantined.pop(fingerprint.lower(), None) is not None

    def reset(self) -> None:
        """Called when the owner unpauses: the breaker re-arms. Quarantines stay until released."""
        self.tripped_at = None
        self.signals.clear()

    def status(self, now: datetime) -> dict[str, Any]:
        recent = [s for s in self.signals if s[0] >= now - self.window]
        return {
            "tripped_at": self.tripped_at.isoformat() if self.tripped_at else None,
            "threshold": self.threshold,
            "window_minutes": int(self.window.total_seconds() // 60),
            "recent_hostile": [{"at": at.isoformat(), "code": code} for at, code, _ in recent],
            "quarantined": [{"invoice_fingerprint": fp, "code": c} for fp, c in self.quarantined.items()],
        }
