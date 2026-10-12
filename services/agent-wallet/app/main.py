"""agent-wallet: guarded execution of financing decisions on a mock ledger or FISCO BCOS (CHAIN_MODE).

Owner: Agent AI engineer. Endpoints follow CLAUDE.md 6.1; models come from shared/schemas.py.
"""

import hmac
import json
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from ledger.mock import MockLedger

from app.guard.classifier import load_classifier
from app.models import ExecuteRequest, load_mandate, load_payees
from app.settings import get_settings
from app.wallet.lifecycle import WalletService
from app.wallet.store import Store
from shared.schemas import (
    MandateActivateRequest,
    WalletApproveRequest,
    WalletConfirmRequest,
    WalletRegisterRequest,
    WalletResult,
    WalletSettleRequest,
)

CONFIG = Path(__file__).resolve().parents[1] / "config"


def _now() -> datetime:
    return datetime.now().astimezone()


def build_ledger(settings, payees: dict, clock: Callable[[], datetime]):
    """The ledger behind CHAIN_MODE: the mock, or the FISCO BCOS adapter on the deployed contracts."""
    if settings.ledger_mode == "mock":
        return MockLedger(clock=clock)
    from ledger.fisco import FiscoLedger

    deployment = json.loads(Path(settings.chain_deployments_file).read_text(encoding="utf-8"))["fisco"]
    keys = {
        "agent": settings.chain_account_key_path,
        "owner": settings.chain_owner_key_path,
        "approver": settings.chain_approver_key_path,
        "risk_oracle": settings.chain_risk_oracle_key_path,
    }
    missing = [role for role, path in keys.items() if not path]
    if missing or not settings.fisco_sdk_dir or not settings.fisco_config_dir:
        raise RuntimeError(
            f"CHAIN_MODE=fisco needs key paths for {missing} and FISCO_SDK_DIR, FISCO_CONFIG_DIR"
        )
    return FiscoLedger(
        deployment,
        keys,
        {party: entry.address for party, entry in payees.items()},
        settings.fisco_sdk_dir,
        settings.fisco_config_dir,
        settings.fisco_receipts_dir,
    )


def build_service(clock: Callable[[], datetime] = _now) -> WalletService:
    settings = get_settings()
    payees = load_payees(CONFIG / "payees.json")
    ledger = build_ledger(settings, payees, clock)
    classifier = load_classifier(settings.injection_model_dir) if settings.injection_model_dir else None
    return WalletService(
        ledger,
        Store(),
        payees,
        settings.platform_fee_rate,
        clock,
        demo_mode=settings.demo_mode,
        canary=settings.agent_canary,
        classifier=classifier,
        classifier_action=settings.injection_classifier_action,
    )


def bootstrap_demo(service: WalletService) -> None:
    """Startup setup for the demo mandate. The mock also seeds lender liquidity (TX-3). On FISCO the deploy
    script has already set the mandate and funded the vault, so startup only checks the chain agrees."""
    settings = get_settings()
    if service.ledger.name == "fisco":
        mandate = load_mandate(CONFIG / "mandate.demo.json")
        onchain = service.ledger.mandate_hash_onchain()
        if onchain.lower() != mandate.mandate_hash.lower():
            raise RuntimeError(
                f"the chain's mandate {onchain} is not the demo mandate {mandate.mandate_hash}"
            )
        service.mandate = mandate
        # A restart starts with an empty store. Count what the chain has already spent, or the off-chain cap
        # would restart from zero. A failed read raises, so the wallet does not start without the cap.
        service.seed_spend(service.ledger.rolling_spend())
        return
    service.activate_mandate(
        load_mandate(CONFIG / "mandate.demo.json").model_dump(mode="json", by_alias=False),
        settings.wallet_max_tx_amount,
        settings.wallet_daily_cap,
    )
    for lender in ("lender_a", "lender_b"):
        service.ledger.deposit(lender, Decimal("5000000.00"))


def _check_token(expected: str | None, given: str | None) -> None:
    if not expected or not given or not hmac.compare_digest(expected, given):
        raise HTTPException(status_code=403, detail="Unauthorized")


def create_app(service: WalletService | None = None) -> FastAPI:
    svc = service or build_service()
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Starts with the demo mandate (and the mock's liquidity), so `uvicorn app.main:app` runs as is.
        if svc.mandate is None:
            bootstrap_demo(svc)
        yield

    app = FastAPI(title="agent-wallet", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "agent-wallet", "ledger": svc.ledger.name}

    @app.post("/wallet/execute", response_model=WalletResult)
    def execute(req: ExecuteRequest, x_agent_token: str | None = Header(default=None)) -> WalletResult:
        _check_token(settings.wallet_agent_token, x_agent_token)  # the agent's calls need the agent token
        if req.skip_offchain_checks and not settings.demo_mode:
            return svc._offchain_block("SchemaInvalid", "L0")  # the bypass exists only with DEMO_MODE=1
        return svc.execute(req)

    @app.post("/wallet/register", response_model=WalletResult)
    def register(
        req: WalletRegisterRequest, x_agent_token: str | None = Header(default=None)
    ) -> WalletResult:
        _check_token(settings.wallet_agent_token, x_agent_token)
        return svc.register(req)

    @app.post("/wallet/approve", response_model=WalletResult)
    def approve(
        req: WalletApproveRequest, x_risk_oracle_token: str | None = Header(default=None)
    ) -> WalletResult:
        _check_token(settings.wallet_risk_oracle_token, x_risk_oracle_token)  # only the risk oracle approves
        return svc.approve(req)

    @app.post("/wallet/settle", response_model=WalletResult)
    def settle(req: WalletSettleRequest, x_agent_token: str | None = Header(default=None)) -> WalletResult:
        _check_token(settings.wallet_agent_token, x_agent_token)
        return svc.settle(req)

    @app.post("/wallet/confirm/{tx_id}", response_model=WalletResult)
    def confirm(
        tx_id: str,
        req: WalletConfirmRequest,
        x_approver_token: str | None = Header(default=None),
    ) -> WalletResult:
        _check_token(settings.wallet_approver_token, x_approver_token)  # the owner token cannot confirm
        return svc.confirm(tx_id, req.approve)

    @app.post("/wallet/pause", response_model=WalletResult)
    def pause(
        x_owner_token: str | None = Header(default=None), x_approver_token: str | None = Header(default=None)
    ):
        if (
            x_approver_token
            and settings.wallet_approver_token
            and hmac.compare_digest(settings.wallet_approver_token, x_approver_token)
        ):
            return svc.pause(True)
        _check_token(settings.wallet_owner_token, x_owner_token)
        return svc.pause(True)

    @app.post("/wallet/unpause", response_model=WalletResult)
    def unpause(x_owner_token: str | None = Header(default=None)) -> WalletResult:
        _check_token(settings.wallet_owner_token, x_owner_token)  # only the owner unpauses
        return svc.pause(False)

    @app.post("/wallet/mandate/activate")
    def activate(req: MandateActivateRequest, x_owner_token: str | None = Header(default=None)) -> dict:
        _check_token(settings.wallet_owner_token, x_owner_token)
        try:
            mandate = svc.activate_mandate(
                {**req.mandate, "mandate_id": req.mandate_id},
                settings.wallet_max_tx_amount,
                settings.wallet_daily_cap,
            )
        except ValueError as err:
            raise HTTPException(status_code=422, detail=f"MandateOutOfBounds: {err}") from err
        return {"mandate_id": mandate.mandate_id, "mandate_hash": mandate.mandate_hash}

    @app.get("/wallet/mandate")
    def get_mandate() -> dict:
        if svc.mandate is None:
            raise HTTPException(status_code=404, detail="no mandate active")
        return {"mandate_id": svc.mandate.mandate_id, "mandate_hash": svc.mandate.mandate_hash}

    @app.get("/wallet/holds")
    def list_holds(x_approver_token: str | None = Header(default=None)) -> dict:
        _check_token(settings.wallet_approver_token, x_approver_token)  # only the approver sees the queue
        return {"holds": svc.list_holds()}

    def _audit_view(entries: list[dict]) -> dict:
        return {"entries": entries, "verified": svc.audit.verify()}  # whole-chain check, not just these rows

    @app.get("/wallet/audit/{invoice_id}")
    def audit_by_invoice(invoice_id: str) -> dict:
        return _audit_view(svc.audit.for_invoice(invoice_id))

    @app.get("/wallet/audit/ref/{audit_ref}")
    def audit_by_ref(audit_ref: str) -> dict:
        return _audit_view(svc.audit.for_ref(audit_ref))

    @app.get("/wallet/tx/{tx_id}", response_model=WalletResult)
    def get_tx(tx_id: str) -> WalletResult:
        found = svc.store.txs.get(tx_id)
        if found is None:
            raise HTTPException(status_code=404, detail="unknown tx_id")
        return found[1]

    return app


app = create_app()
