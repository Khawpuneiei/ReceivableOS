"""Signed credit decisions: the wallet checks policy-ai's Ed25519 signature at approval (TX-2).

Owner: Agent AI engineer.

Known limit before this: the decision was checked by hash only, so whoever held the risk-oracle token could
approve a decision they wrote themselves. With a signer configured, an approval also needs
`X-Decision-Signature: ed25519:<key_id>:<base64 signature>` over

    receivableos/decision/v1|<decision_hash>|<invoice_fingerprint>

made with a key that lives in policy-ai, not in the wallet. The fingerprint is part of the message, so a
signed decision cannot be replayed onto another invoice. The draw then has to carry the approved hash (L1), so
the signature covers the money too. Public keys are not secrets and sit in config/decision_signers.json.

`enforce: false` (the default, until policy-ai signs) checks a signature only when one is sent.
"""

import base64
import binascii
import json
from dataclasses import dataclass, field
from pathlib import Path

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

DOMAIN = "receivableos/decision/v1"


def message(decision_hash: str, invoice_fingerprint: str) -> bytes:
    return f"{DOMAIN}|{decision_hash.lower()}|{invoice_fingerprint.lower()}".encode("utf-8")


@dataclass
class DecisionSigners:
    enforce: bool = False
    keys: dict[str, bytes] = field(default_factory=dict)  # key_id -> raw 32-byte Ed25519 public key

    @classmethod
    def load(cls, path: Path) -> "DecisionSigners":
        if not path.is_file():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        keys = {key_id: bytes.fromhex(pub) for key_id, pub in raw.get("signers", {}).items()}
        return cls(enforce=bool(raw.get("enforce", False)), keys=keys)

    def check(self, header: str | None, decision_hash: str, invoice_fingerprint: str) -> str | None:
        """None when the approval may proceed, else the L1 reason code."""
        if not header:
            return "DecisionUnsigned" if self.enforce else None
        try:
            scheme, key_id, sig_b64 = header.split(":", 2)
            signature = base64.b64decode(sig_b64, validate=True)
        except (ValueError, binascii.Error):
            return "DecisionSignatureInvalid"
        if scheme != "ed25519":
            return "DecisionSignatureInvalid"
        public = self.keys.get(key_id)
        if public is None:
            return "DecisionSignerUnknown"
        verifier = eddsa.new(eddsa.import_public_key(public), "rfc8032")
        try:
            verifier.verify(message(decision_hash, invoice_fingerprint), signature)
        except ValueError:
            return "DecisionSignatureInvalid"
        return None


def sign(private_pem: str, key_id: str, decision_hash: str, invoice_fingerprint: str) -> str:
    """The header value policy-ai would send. Used by scripts/decision_keys.py and the tests."""
    signer = eddsa.new(ECC.import_key(private_pem), "rfc8032")
    signature = signer.sign(message(decision_hash, invoice_fingerprint))
    return f"ed25519:{key_id}:{base64.b64encode(signature).decode('ascii')}"
