"""policy-ai: financing policy and credit risk model.

Stub: returns the fixed demo decision from docs/02-finance-domain.md.
Replace the body of `decide` with the real policy and model.
"""

from decimal import Decimal

from fastapi import FastAPI

from shared.schemas import Decision, PolicyDecision, PolicyRequest

app = FastAPI(title="policy-ai")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "policy-ai"}


@app.post("/policy/decide", response_model=PolicyDecision)
def decide(req: PolicyRequest) -> PolicyDecision:
    advance_rate = Decimal("0.70")
    return PolicyDecision(
        decision=Decision.approve,
        advance_rate=advance_rate,
        limit=(req.invoice.amount * advance_rate).quantize(Decimal("0.01")),
        fee_rate=Decimal("0.009"),
        risk_score=0.18,
        reasons=["stub: policy not implemented yet"],
        model_version="stub",
        policy_version="stub",
    )
