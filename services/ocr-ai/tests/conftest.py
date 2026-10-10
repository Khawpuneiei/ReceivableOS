"""Every API test has independent secrets and bounded local state."""

import secrets

import pytest
from fastapi.testclient import TestClient

from app.cache import JsonCache
from app.main import app


@pytest.fixture(autouse=True)
def isolated_candidate_caches(monkeypatch):
    monkeypatch.setattr("app.qwen._cache", JsonCache())
    monkeypatch.setattr("app.llm_client._cache", JsonCache())
    monkeypatch.delenv("LLM_API_KEY", raising=False)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("FINGERPRINT_HMAC_KEY", secrets.token_hex(32))
    monkeypatch.setenv("BANK_TOKEN_HMAC_KEY", secrets.token_hex(32))
    monkeypatch.setenv("OCR_STATE_PATH", str(tmp_path / "state.sqlite"))
    monkeypatch.setenv("OCR_PADDLE_ENABLED", "0")
    monkeypatch.setenv("OCR_QWEN_ENABLED", "0")
    with TestClient(app) as result:
        yield result
