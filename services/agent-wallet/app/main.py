"""agent-wallet: guarded execution of financing decisions on FISCO BCOS or a mock ledger.

Stub: never signs anything. Replace the body of `execute` with the guard and ledger calls.
"""

import uuid

from fastapi import FastAPI

from shared.schemas import Decision, TxStatus, WalletRequest, WalletResult

app = FastAPI(title="agent-wallet")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "agent-wallet"}


@app.post("/wallet/execute", response_model=WalletResult)
def execute(req: WalletRequest) -> WalletResult:
    status = TxStatus.rejected if req.decision.decision != Decision.approve else TxStatus.pending_approval
    return WalletResult(
        tx_id=f"stub-{uuid.uuid4().hex[:12]}",
        status=status,
        chain_ref=None,
        approvals_required=1,
        audit_ref=f"audit-{req.invoice_id}",
    )
