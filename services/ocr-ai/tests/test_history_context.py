"""Key/recipe changes cannot silently bypass persisted duplicate evidence."""

import os
import sqlite3
from pathlib import Path

import pytest

from app.config import Settings
from app.fingerprint import history_context
from app.history import HistoryContextError, InvoiceObservation, ObservationStore

REPO = Path(__file__).resolve().parents[3]


def post(client, name, **headers):
    raw = (REPO / "data/invoices/demo" / name).read_bytes()
    return client.post("/ocr/extract", files={"file": (name, raw, "application/pdf")}, headers=headers)


@pytest.mark.parametrize("change", ["fingerprint", "bank", "recipe", "unversioned"])
@pytest.mark.parametrize("retry", [False, True])
def test_changed_context_refuses_new_upload_and_retry_without_writing(client, monkeypatch, change, retry):
    first = post(client, "01_happy.pdf", **{"Idempotency-Key": "first-attempt"})
    assert first.status_code == 200 and first.json()["fraud_score"] == 0
    path = Path(os.environ["OCR_STATE_PATH"])
    if change == "recipe":
        monkeypatch.setattr("app.fingerprint.HISTORY_CONTEXT_VERSION", "future-recipe")
    elif change == "unversioned":
        with sqlite3.connect(path) as connection:
            connection.execute("DROP TABLE history_metadata")
    else:
        monkeypatch.setenv(
            "FINGERPRINT_HMAC_KEY" if change == "fingerprint" else "BANK_TOKEN_HMAC_KEY", "changed-test-key"
        )
    response = post(
        client,
        "01_happy.pdf" if retry else "04_duplicate.pdf",
        **{"Idempotency-Key": "first-attempt" if retry else "new-attempt"},
    )
    assert response.status_code == 503, response.text
    assert "migration" in response.json()["detail"]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 1


def test_same_context_after_restart_preserves_duplicate_detection(client):
    first = post(client, "01_happy.pdf")
    assert first.status_code == 200
    settings = Settings.from_env()
    reopened = ObservationStore(
        settings.state_path, context_digest=history_context(settings.fingerprint_key, settings.bank_key)
    )
    assert len(reopened.observations()) == 1
    second = post(client, "04_duplicate.pdf")
    assert second.status_code == 200
    assert second.json()["fraud_flags"] == ["duplicate_fingerprint"]
    assert second.json()["fraud_score"] == 0.8


def test_dev_reset_explicitly_allows_new_context(client, monkeypatch):
    assert post(client, "01_happy.pdf").status_code == 200
    path = Path(os.environ["OCR_STATE_PATH"])
    store = ObservationStore(path)
    with pytest.raises(PermissionError):
        store.reset(development_mode=False, allow_reset=True)
    monkeypatch.setenv("FINGERPRINT_HMAC_KEY", "new-demo-test-key")
    assert post(client, "04_duplicate.pdf").status_code == 503
    store.reset(development_mode=True, allow_reset=True)
    response = post(client, "04_duplicate.pdf")
    assert response.status_code == 200 and response.json()["fraud_score"] == 0


def test_key_context_is_opaque_and_missing_context_cannot_write(tmp_path):
    context = history_context("private-fingerprint-test-key", "private-bank-test-key")
    path = tmp_path / "history.sqlite"
    store = ObservationStore(path, context_digest=context)
    record = InvoiceObservation(doc_hash="sha256:" + "a" * 64)
    store.observe(record, request_digest=record.doc_hash)
    raw = path.read_bytes()
    assert b"private-fingerprint-test-key" not in raw and b"private-bank-test-key" not in raw
    with pytest.raises(HistoryContextError):
        ObservationStore(path).observe(record, request_digest=record.doc_hash)


def test_stale_store_rechecks_context_inside_each_transaction(tmp_path):
    path = tmp_path / "history.sqlite"
    first = ObservationStore(path, context_digest="sha256:" + "a" * 64)
    other = ObservationStore(path, context_digest="sha256:" + "b" * 64)
    record = InvoiceObservation(doc_hash="sha256:" + "c" * 64)
    first.observe(record, request_digest=record.doc_hash)
    first.reset(development_mode=True, allow_reset=True)
    other.observe(record, request_digest=record.doc_hash)
    with pytest.raises(HistoryContextError):
        first.observe(record, request_digest=record.doc_hash)
    with pytest.raises(HistoryContextError):
        first.observations()
    assert len(other.observations()) == 1
