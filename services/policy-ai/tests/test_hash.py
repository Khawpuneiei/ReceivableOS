"""decision_hash must match the agent wallet's tamper check (open PR #17, app/guard/pipeline.py L1)."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from Crypto.Hash import keccak
from factories import happy_body

from app.decision import decide
from app.hashing import canonical_json, decision_hash, keccak256_hex
from app.schemas import PolicyRequestExt
from shared.schemas import PolicyDecision

NOW = datetime(2026, 10, 12, 3, 0, tzinfo=timezone.utc)


class WalletDecisionView(PolicyDecision):
    """What the wallet parses the decision into: the shared model plus an optional valid_until."""

    valid_until: datetime | None = None


def wallet_recompute(decision_json: dict) -> str:
    """The wallet's L1 check, written out independently of app.hashing."""
    decision = WalletDecisionView.model_validate(decision_json)
    view = decision.model_dump(mode="json", exclude={"decision_hash", "valid_until"})
    text = json.dumps(view, sort_keys=True, separators=(",", ":"))
    return "0x" + keccak.new(digest_bits=256, data=text.encode("utf-8")).hexdigest()


def _decide(body: dict, now: datetime = NOW):
    return decide(PolicyRequestExt.model_validate(body), now=now)


def test_keccak256_is_not_sha3():
    empty = "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert keccak256_hex("") == empty
    assert "0x" + hashlib.sha3_256(b"").hexdigest() != empty


def test_canonical_json_is_sorted_and_compact():
    assert canonical_json({"b": 1, "a": [1, {"d": "x", "c": None}]}) == '{"a":[1,{"c":null,"d":"x"}],"b":1}'


def test_hash_recomputes_the_way_the_wallet_does():
    d = _decide(happy_body())
    body = json.loads(d.model_dump_json())  # what goes over the wire
    assert d.decision_hash == wallet_recompute(body) == decision_hash(body)
    assert d.decision_hash.startswith("0x") and len(d.decision_hash) == 66


def test_same_request_gives_the_same_id_and_hash():
    first, again = _decide(happy_body()), _decide(happy_body(), now=NOW + timedelta(minutes=5))
    assert (first.decision_id, first.decision_hash) == (again.decision_id, again.decision_hash)
    assert first.valid_until != again.valid_until  # wall clock, outside the hash


def test_changing_the_request_changes_the_hash():
    base = _decide(happy_body())
    body = happy_body()
    body["supplier_profile"]["years_trading"] = 4  # changes no term, only the request
    other = _decide(body)
    assert other.limit == base.limit
    assert other.request_hash != base.request_hash
    assert (other.decision_id, other.decision_hash) != (base.decision_id, base.decision_hash)


def test_tampering_with_a_shared_field_breaks_the_hash():
    body = json.loads(_decide(happy_body()).model_dump_json())
    for field, value in [("limit", "599200.00"), ("decision", "review"), ("reasons", [])]:
        tampered = {**body, field: value}
        assert wallet_recompute(tampered) != body["decision_hash"], field


def test_policy_only_fields_are_outside_the_hash():
    body = json.loads(_decide(happy_body()).model_dump_json())
    extended = {**body, "rule_trace": [], "valid_until": "2030-01-01T00:00:00Z", "reason_details": []}
    assert wallet_recompute(extended) == body["decision_hash"]
