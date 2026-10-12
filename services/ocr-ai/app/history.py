"""Bounded SQLite observations, separate from financing and PO allocation ledgers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field, TypeAdapter

from app.models import CurrencyCode, Digest, EvidenceId, EvidenceReference, Fingerprint, LocalModel

EntityToken = Annotated[str, Field(pattern=r"^entity:v1:[0-9a-f]{64}$")]
BankToken = Annotated[str, Field(pattern=r"^bank:v[12]:[0-9a-f]{64}$")]


class HistoryConflictError(ValueError):
    """An idempotency key was reused with different request bytes."""


class HistoryCapacityError(ValueError):
    """The bounded observation store needs operator attention."""


class HistoryContextError(ValueError):
    """Persisted identities cannot safely be compared under another key/recipe."""


class InvoiceObservation(LocalModel):
    doc_hash: Digest
    semantic_fingerprint: Fingerprint | None = None
    invoice_number: str | None = Field(default=None, max_length=200)
    amount: Decimal | None = None
    currency: CurrencyCode | None = None
    issue_date: date | None = None
    supplier_token: EntityToken | None = None
    buyer_token: EntityToken | None = None
    bank_token: BankToken | None = None
    evidence_refs: list[EvidenceId] = Field(default_factory=list, max_length=32)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=32)
    anomaly_codes: list[str] = Field(default_factory=list, max_length=32)
    rule_version: Literal["history-v1"] = "history-v1"


class DuplicateObservation(LocalModel):
    code: Literal["duplicate_invoice_hash", "duplicate_fingerprint"]
    previous_observation_id: str
    previous_doc_hash: Digest
    evidence_refs: list[EvidenceId]


class HistoryResult(LocalModel):
    observation_id: str
    replayed: bool
    duplicates: list[DuplicateObservation]


class ObservationStore:
    def __init__(
        self, path: Path, *, max_observations: int = 1000, context_digest: str | None = None
    ) -> None:
        if max_observations < 1:
            raise ValueError("Observation limit must be positive")
        self.path = path
        self.max_observations = max_observations
        self.context_digest = TypeAdapter(Digest).validate_python(context_digest) if context_digest else None
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    observation_id TEXT PRIMARY KEY,
                    doc_hash TEXT NOT NULL,
                    fingerprint TEXT,
                    observed_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS observations_hash ON observations(doc_hash);
                CREATE INDEX IF NOT EXISTS observations_fingerprint ON observations(fingerprint);
                CREATE TABLE IF NOT EXISTS requests (
                    key_hash TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
                    result TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS history_metadata (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def _ensure_context(self, connection) -> None:
        if self.context_digest is None:
            raise HistoryContextError("Observation writes require an identity context")
        prior = connection.execute(
            "SELECT value FROM history_metadata WHERE name = 'identity_context'"
        ).fetchone()
        if prior:
            if prior["value"] != self.context_digest:
                raise HistoryContextError("History identity context changed; operator migration is required")
        elif connection.execute(
            "SELECT EXISTS(SELECT 1 FROM observations) OR EXISTS(SELECT 1 FROM requests)"
        ).fetchone()[0]:
            raise HistoryContextError(
                "History identity context is unversioned; operator migration is required"
            )
        else:
            connection.execute(
                "INSERT INTO history_metadata VALUES ('identity_context', ?)", (self.context_digest,)
            )

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def observe(
        self,
        observation: InvoiceObservation,
        *,
        request_digest: Digest,
        idempotency_key: str | None = None,
    ) -> HistoryResult:
        """Atomically detect prior observations and add one; same-key retries do not add rows."""
        observation = InvoiceObservation.model_validate(observation.model_dump())
        # Validate request metadata even for calls made outside the HTTP boundary.
        request_digest = TypeAdapter(Digest).validate_python(request_digest)
        if idempotency_key is not None and (not idempotency_key or len(idempotency_key) > 200):
            raise ValueError("Idempotency key must contain between 1 and 200 characters")
        key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest() if idempotency_key else None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_context(connection)
            if key_hash:
                prior = connection.execute(
                    "SELECT request_digest, result FROM requests WHERE key_hash = ?", (key_hash,)
                ).fetchone()
                if prior:
                    if prior["request_digest"] != request_digest:
                        raise HistoryConflictError("Idempotency key is already bound to another request")
                    result = HistoryResult.model_validate_json(prior["result"])
                    return result.model_copy(update={"replayed": True})
            count = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            if count >= self.max_observations:
                raise HistoryCapacityError("OCR observation history is at capacity; review is required")
            prior_rows = connection.execute(
                "SELECT observation_id, doc_hash, fingerprint, payload FROM observations "
                "WHERE doc_hash = ? OR (? IS NOT NULL AND fingerprint = ?) ORDER BY rowid",
                (observation.doc_hash, observation.semantic_fingerprint, observation.semantic_fingerprint),
            ).fetchall()
            duplicates = []
            for row in prior_rows:
                refs = json.loads(row["payload"])["evidence_refs"]
                for code, triggered in (
                    ("duplicate_invoice_hash", row["doc_hash"] == observation.doc_hash),
                    (
                        "duplicate_fingerprint",
                        observation.semantic_fingerprint is not None
                        and row["fingerprint"] == observation.semantic_fingerprint,
                    ),
                ):
                    if triggered:
                        duplicates.append(
                            DuplicateObservation(
                                code=code,
                                previous_observation_id=row["observation_id"],
                                previous_doc_hash=row["doc_hash"],
                                evidence_refs=refs,
                            )
                        )
            result = HistoryResult(observation_id=f"obs_{uuid4().hex}", replayed=False, duplicates=duplicates)
            connection.execute(
                "INSERT INTO observations VALUES (?, ?, ?, ?, ?)",
                (
                    result.observation_id,
                    observation.doc_hash,
                    observation.semantic_fingerprint,
                    datetime.now(timezone.utc).isoformat(),
                    observation.model_dump_json(),
                ),
            )
            if key_hash:
                connection.execute(
                    "INSERT INTO requests VALUES (?, ?, ?, ?)",
                    (key_hash, request_digest, result.observation_id, result.model_dump_json()),
                )
            return result

    def observations(self) -> list[tuple[str, InvoiceObservation]]:
        with self._connect() as connection:
            # Check and read in one transaction, including when another process resets/rebinds.
            if self.context_digest is not None:
                connection.execute("BEGIN IMMEDIATE")
                self._ensure_context(connection)
            rows = connection.execute(
                "SELECT observation_id, payload FROM observations ORDER BY rowid"
            ).fetchall()
        return [
            (row["observation_id"], InvoiceObservation.model_validate_json(row["payload"])) for row in rows
        ]

    def reset(self, *, development_mode: bool, allow_reset: bool) -> None:
        if not development_mode or not allow_reset:
            raise PermissionError("History reset requires explicit development mode and reset permission")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM requests")
            connection.execute("DELETE FROM observations")
            connection.execute("DELETE FROM history_metadata WHERE name = 'identity_context'")
