"""Wallet settings from environment variables (CLAUDE.md 8.3). Owner: Agent AI engineer.

Keys, tokens and HMAC secrets have no defaults here: they come from `.env` only and are never logged.
Money settings are THB with 2 decimals and act as platform ceilings; a mandate can only tighten them.
"""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    wallet_url: str = "http://localhost:8003"
    settlement_token: str = "tTHB"

    # Chain: mock needs no node; fisco needs a running FISCO BCOS node
    chain_mode: Literal["mock", "fisco"] = "mock"
    chain_rpc_url: str = "http://127.0.0.1:20200"
    chain_group_id: str = "group0"
    chain_deployments_file: str = "./services/agent-wallet/contracts/deployments.json"
    chain_account_key_path: str | None = None  # agent key: may call AgentWallet.execute only
    chain_owner_key_path: str | None = None  # mandate owner
    chain_approver_key_path: str | None = None  # Finance approver: confirm and pause
    chain_risk_oracle_key_path: str | None = None  # signs Registry.approve (TX-2)

    # Money: THB, 2 decimals, platform ceilings
    wallet_currency: str = "THB"
    wallet_amount_decimals: int = 2
    wallet_max_tx_amount: Decimal = Decimal("1500000.00")
    wallet_daily_cap: Decimal = Decimal("3000000.00")
    wallet_human_review_above: Decimal = Decimal("837500.00")
    wallet_payee_allowlist: str | None = None

    # Tokens, the fingerprint key and flags
    wallet_owner_token: str | None = None
    wallet_approver_token: str | None = None
    wallet_risk_oracle_token: str | None = None  # X-Risk-Oracle-Token for POST /wallet/approve (TX-2)
    fingerprint_hmac_key: str | None = None  # same value as ocr-ai
    agent_canary: str | None = None
    injection_model_dir: str | None = None  # local folder with the pinned classifier; unset = rules only
    # log (default): classifier flags are audited only. hold: flags wait for an approver. block: flags reject.
    injection_classifier_action: Literal["log", "hold", "block"] = "log"
    platform_fee_rate: Decimal = Decimal("0.003")
    demo_mode: bool = False  # enables the skip_offchain_checks bypass for on-stage reverts

    # LLM: optional; the deterministic picker runs when unset
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
