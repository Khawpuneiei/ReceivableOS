"""policy-ai: financing policy and credit risk model (services/policy-ai/CLAUDE.md).

POST /policy/decide runs the YAML rule set and the PD model (app/model.py); no LLM is called on this path.
GET /policy/rules returns the active rule set for the dashboard.
POST /policy/mandate/compile turns the SME's sentence into a validated mandate (app/mandate.py).
"""

import logging

from fastapi import FastAPI, HTTPException

from app import decision, mandate, model
from app.rules import active_rules
from app.schemas import PolicyDecisionExt, PolicyRequestExt

log = logging.getLogger("policy-ai")
app = FastAPI(title="policy-ai")
decision.default_mandate()  # load and check the default mandate now, so a bad file stops startup


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "policy-ai",
        "policy_version": active_rules().version,
        "model_version": model.active().version,
    }


@app.get("/policy/rules")
def policy_rules() -> dict:
    rules = active_rules()
    return {"version": rules.version, "rules": rules.model_dump(mode="json")}


@app.post("/policy/decide", response_model=PolicyDecisionExt)
def decide(req: PolicyRequestExt) -> PolicyDecisionExt:
    try:
        result = decision.decide(req)
    except decision.InvalidRequest as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    # ids and outcome only: no profile or invoice text in the logs
    log.info(
        "decision_id=%s invoice_id=%s decision=%s decision_hash=%s",
        result.decision_id,
        req.invoice.invoice_id,
        result.decision.value,
        result.decision_hash,
    )
    return result


@app.post("/policy/mandate/compile")
def compile_mandate(req: mandate.CompileRequest) -> dict:
    try:
        return mandate.compile_mandate(req.text, mandate_id=req.mandate_id)
    except mandate.MandateRejected as exc:
        raise HTTPException(status_code=422, detail=[v.as_dict() for v in exc.violations]) from None
