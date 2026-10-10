"""Canonical JSON and the hashes that bind a decision (services/policy-ai/CLAUDE.md section 5.2).

decision_hash mirrors the agent wallet's tamper check (open PR #17: app/models.py canonical_hash and the L1
check in app/guard/pipeline.py): keccak256 over the canonical JSON of the decision as the shared
PolicyDecision, without decision_hash. The wallet parses our response into that model, so the extra
policy-ai fields (rule_trace, valid_until, ...) are dropped on its side and must not be hashed here either.
Note that keccak256 is not hashlib.sha3_256 (different padding).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from Crypto.Hash import keccak
from pydantic import BaseModel

from shared.schemas import PolicyDecision


def canonical_json(obj: Any) -> str:
    """Team-wide canonical form: sorted keys, no spaces. Pass model_dump(mode="json") output."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def keccak256_hex(text: str) -> str:
    return "0x" + keccak.new(digest_bits=256, data=text.encode("utf-8")).hexdigest()


def sha256_hex(text: str) -> str:
    return "0x" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def decision_hash(decision: BaseModel | dict) -> str:
    """keccak256 of the shared-contract view of a decision, exactly as the wallet recomputes it."""
    data = decision.model_dump(mode="json") if isinstance(decision, BaseModel) else decision
    view = PolicyDecision.model_validate(data).model_dump(
        mode="json", exclude={"decision_hash", "valid_until"}
    )
    return keccak256_hex(canonical_json(view))
