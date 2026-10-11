# Orchestrator integration (proposal for the PM)

Status: **proposal.** Nothing here is applied to `services/orchestrator` or `services/policy-ai`, which are
owned by the PM and the policy engineer. The sequence follows CLAUDE.md §8.1 and §6.1.

## What the orchestrator does today

`POST /flow/run` runs OCR, then a duplicate check, then policy, then calls `POST /wallet/execute` with
`payee: "0xSUPPLIER"`, `amount` set to the decision limit, and `invoice_id`. It sends no `invoice_fingerprint`,
no `decision_hash`, and no register or approve step.

We ran this with all four services up. The wallet returned `blocked` with `SchemaInvalid` at L0, and no money moved.
The draw was rejected while building the request, before the payee and guard checks ran.

## Proposed sequence

**1. OCR result → register (TX-1)**

```json
POST /wallet/register
{
  "idempotency_key": "<invoice_id>:register",
  "invoice_id": "<ocr.invoice_id>",
  "invoice_fingerprint": "<ocr.invoice_fingerprint>",
  "doc_hash": "<ocr.doc_hash>",
  "face_value": "<ocr.amount>",
  "currency": "<ocr.currency>",
  "due_date": "<ocr.due_date>",
  "seller": "SELLER:siam-fresh-pack"
}
```

`seller` is the registry id. Never send an address: the payee registry is the only source of payees.

**2. Policy decision → approve (TX-2)**, only when `decision == "approve"`. Send the header `X-Risk-Oracle-Token`. The
wallet refuses the approval unless `decision` is the decision it names, its hash recomputes, and `limit` and
`fee_rate` equal the decision's.

```json
POST /wallet/approve
{
  "idempotency_key": "<invoice_id>:approve",
  "decision_id": "<decision.decision_id>",
  "decision": "<the whole policy decision object>",
  "decision_hash": "<decision.decision_hash>",
  "invoice_fingerprint": "<ocr.invoice_fingerprint>",
  "limit": "<decision.limit>",
  "fee_rate": "<decision.fee_rate>",
  "model_version": "<decision.model_version>",
  "policy_version": "<decision.policy_version>"
}
```

**3. Lender selection** (mock lenders in the orchestrator, per CLAUDE.md §1). Pick the quote with the highest advance
whose APR is at most 12%. Take its `lender_id` and APR. The draw amount is the quoted advance, not `decision.limit`.

**4. Draw (TX-4)**

```json
POST /wallet/execute
{
  "idempotency_key": "<invoice_id>:draw",
  "invoice_id": "<ocr.invoice_id>",
  "invoice_fingerprint": "<ocr.invoice_fingerprint>",
  "decision": { "...the full decision, including decision_id and decision_hash..." },
  "decision_id": "<decision.decision_id>",
  "decision_hash": "<decision.decision_hash>",
  "payee": "SELLER:siam-fresh-pack",
  "amount": "<quoted advance>",
  "currency": "THB",
  "apr": "<lender APR>",
  "lender_id": "<quote.lender_id>",
  "mandate_id": "mdt_001"
}
```

`mandate_id` must be `mdt_001`, the demo mandate the wallet activates at startup. The orchestrator's default form value
`mandate-v0.1` matches nothing.

**5. Buyer paid → settle (TX-5)**

```json
POST /wallet/settle
{
  "idempotency_key": "<invoice_id>:settle",
  "invoice_id": "<ocr.invoice_id>",
  "invoice_fingerprint": "<ocr.invoice_fingerprint>",
  "amount_paid": "<buyer payment>",
  "paid_at": "<date>"
}
```

**6. Show the trail.** `GET /wallet/audit/{invoice_id}` returns the entries and `verified`.

## What each service must provide

- **Policy-ai:** `decision_id` (a string) and `decision_hash` on every decision. The stub returns both as `null`.
- **OCR:** `invoice_fingerprint` and `doc_hash`. The stub already sends both.
- **Orchestrator:** steps 1 to 6 and the lender selection, using `mdt_001`.

## Decision-hash recipe (the wallet recomputes this)

```
decision_hash = keccak256( canonical_json( PolicyDecision.model_dump(mode="json", exclude={"decision_hash"}) ) )
canonical_json(obj) = json.dumps(obj, sort_keys=True, separators=(",", ":"))
```

`PolicyDecision` is `shared/schemas.py`. Set `decision_id` before hashing, because it is part of the hashed object.
`services/agent-wallet/app/models.py` (`canonical_hash`) is the reference implementation. Changing any field after
hashing, even `limit`, makes the wallet return `DecisionTampered`.

## What is verified

- The sequence register → approve → execute → settle runs against the wallet in `scripts/demo.py`. That script builds
  the decision hash the same way the recipe above does.
- **Not verified:** the orchestrator running with real OCR and policy services. The stubs don't produce `decision_id`
  or `decision_hash`, so the current run stays blocked.

## Open questions for the PM

- Who generates the lender quotes? CLAUDE.md puts them in the orchestrator, and there is no `lenders.yaml` in the repo yet.
- Confirm `mdt_001` as the demo mandate ID, or name another.
- Confirm the idempotency key convention `<invoice_id>:<action>`.
