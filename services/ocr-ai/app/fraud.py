"""Explainable deterministic duplicate and scoped shared-account graph signals."""

import math
from decimal import Decimal
from statistics import median

import networkx as nx

from app.config import ANOMALY_FAMILIES, FRAUD_WEIGHTS, MAX_OBSERVATIONS
from app.graph import build_graph
from app.history import InvoiceObservation
from app.models import FraudFinding
from app.normalize import normalize_reference

# An amount this many times the pair's median, after at least this many prior invoices, is an outlier.
OUTLIER_RATIO = Decimal(3)
OUTLIER_MIN_HISTORY = 3


def finding(code: str, reason: str, refs=None, entities=None, path=None) -> FraudFinding:
    return FraudFinding(
        code=code,
        weight=FRAUD_WEIGHTS[code],
        reason=reason,
        evidence_refs=list(dict.fromkeys(refs or []))[:128],
        entity_refs=entities or [],
        path=path or [],
    )


def graph_findings(records: list[tuple[str, InvoiceObservation]], current_id: str) -> list[FraudFinding]:
    if len(records) > MAX_OBSERVATIONS:
        raise ValueError("Graph observation bound exceeded")
    graph = build_graph(records)
    by_id = dict(records)
    current = by_id[current_id]
    signals = []
    if current.supplier_token and current.bank_token:
        prior_supplier_accounts = [
            (oid, record)
            for oid, record in records
            if oid != current_id and record.supplier_token == current.supplier_token and record.bank_token
        ]
        if prior_supplier_accounts:
            previous_id, previous = prior_supplier_accounts[-1]
            if current.bank_token != previous.bank_token:
                signals.append(
                    finding(
                        "bank_account_changed",
                        "The same scoped supplier entity is associated with a different bank token "
                        "than its most recent prior observation; verify the payee change independently",
                        [*current.evidence_refs, *previous.evidence_refs],
                        entities=[current.supplier_token],
                        path=[current_id, previous_id],
                    )
                )
    if current.bank_token and current.supplier_token:
        peers = [
            (oid, record)
            for oid, record in records
            if record.bank_token == current.bank_token
            and record.supplier_token
            and record.supplier_token != current.supplier_token
        ]
        if peers:
            previous_id, peer = peers[0]
            component = nx.Graph()
            for source, target, data in graph.edges(data=True):
                if data["edge_type"] in {"ISSUED_BY", "PAYABLE_TO"}:
                    component.add_edge(source, target, **data)
            path = nx.shortest_path(component, current_id, previous_id)
            refs = list(dict.fromkeys([*current.evidence_refs, *peer.evidence_refs]))
            signals.append(
                finding(
                    "shared_bank_token",
                    "Distinct scoped legal entities reference one bank token; "
                    "the relationship requires contextual review",
                    refs,
                    path[1:-1],
                    path,
                )
            )
            cluster = [(oid, record) for oid, record in records if record.bank_token == current.bank_token]
            anomalies = [record for _, record in cluster if record.anomaly_codes]
            families = {
                ANOMALY_FAMILIES[code]
                for record in anomalies
                for code in record.anomaly_codes
                if code in ANOMALY_FAMILIES
            }
            entities = {record.supplier_token for record in anomalies if record.supplier_token}
            if len(anomalies) >= 2 and len(families) >= 2 and len(entities) >= 2:
                signals.append(
                    finding(
                        "suspicious_cluster",
                        "A shared-account component contains distinct legal "
                        "entities and multiple independent document anomalies; not proof of fraud",
                        list(dict.fromkeys(ref for record in anomalies for ref in record.evidence_refs)),
                        sorted(entities),
                        path,
                    )
                )
    for oid, previous in records:
        if oid == current_id or not current.supplier_token or not current.buyer_token:
            continue
        scoped = (
            current.supplier_token == previous.supplier_token
            and current.buyer_token == previous.buyer_token
            and current.currency == previous.currency
            and current.issue_date == previous.issue_date
            and current.invoice_number
            and previous.invoice_number
        )
        if scoped and normalize_reference(current.invoice_number) == normalize_reference(
            previous.invoice_number
        ):
            if (
                current.amount is not None
                and previous.amount is not None
                and current.amount != previous.amount
            ):
                signals.append(
                    finding(
                        "near_duplicate",
                        "Same scoped parties, invoice reference, currency, and "
                        "issue date have different amounts; review the candidate similarity",
                        [*current.evidence_refs, *previous.evidence_refs],
                        path=[current_id, oid],
                    )
                )
                break
    if current.amount is not None and current.supplier_token and current.buyer_token:
        prior = [
            (oid, record)
            for oid, record in records
            if oid != current_id
            and record.doc_hash != current.doc_hash
            and record.supplier_token == current.supplier_token
            and record.buyer_token == current.buyer_token
            and record.currency == current.currency
            and record.amount is not None
            and record.amount > 0
        ]
        if len(prior) >= OUTLIER_MIN_HISTORY:
            typical = median(record.amount for _, record in prior)
            if current.amount >= OUTLIER_RATIO * typical:
                signals.append(
                    finding(
                        "amount_outlier",
                        f"Amount is at least {OUTLIER_RATIO}x the median of {len(prior)} prior invoices "
                        "between the same scoped supplier and buyer; confirm the order independently",
                        [
                            *current.evidence_refs,
                            *(ref for _, record in prior[-3:] for ref in record.evidence_refs),
                        ],
                        entities=[current.supplier_token, current.buyer_token],
                        path=[current_id, *(oid for oid, _ in prior[-3:])],
                    )
                )
    return signals


def score(findings: list[FraudFinding]) -> float:
    # Repeated evidence for one code does not repeatedly increase the score.
    weights = {item.code: item.weight for item in findings}
    return round(1 - math.prod(1 - weight for weight in weights.values()), 3)
