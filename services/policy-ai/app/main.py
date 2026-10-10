"""policy-ai: financing policy and credit risk model.

Stub: sends everything to review with a conservative advance.
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
    advance_rate = 0.7
    return PolicyDecision(
        decision=Decision.review,
        advance_rate=advance_rate,
        limit=(req.invoice.amount * Decimal(str(advance_rate))).quantize(Decimal("0.01")),
        fee_rate=0.02,
        risk_score=0.5,
        reasons=["stub: policy not implemented yet"],
    )
