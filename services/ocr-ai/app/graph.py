"""One typed observation graph for risk rules and finding-scoped consumer evidence."""

import networkx as nx

from app.config import MAX_OBSERVATIONS
from app.history import InvoiceObservation
from app.models import FraudFinding, FraudGraph, GraphEdge, GraphNode


def build_graph(records: list[tuple[str, InvoiceObservation]]) -> nx.MultiDiGraph:
    if len(records) > MAX_OBSERVATIONS or len(dict(records)) != len(records):
        raise ValueError("Invalid graph observation set")
    graph = nx.MultiDiGraph()
    for observation_id, record in records:
        graph.add_node(observation_id, node_type="invoice", doc_hash=record.doc_hash)
        for relation, entity in (("ISSUED_BY", record.supplier_token), ("BILLED_TO", record.buyer_token)):
            if entity:
                graph.add_node(entity, node_type="company")
                graph.add_edge(
                    observation_id,
                    entity,
                    edge_type=relation,
                    evidence_refs=record.evidence_refs,
                    observation_id=observation_id,
                )
        if record.bank_token and record.supplier_token:
            graph.add_node(record.bank_token, node_type="bank_account_token")
            graph.add_edge(
                record.supplier_token,
                record.bank_token,
                edge_type="PAYABLE_TO",
                evidence_refs=record.evidence_refs,
                observation_id=observation_id,
            )
    return graph


def export_graph(records, current_id: str, findings: list[FraudFinding]) -> FraudGraph:
    """Expose implicated observations, never a dump of unrelated history."""
    graph = build_graph(records)
    if current_id not in graph:
        raise ValueError("Current observation is unresolved")
    implicated_refs = {ref for item in findings for ref in item.evidence_refs}
    selected = {current_id}
    selected.update(node for item in findings for node in [*item.path, *item.entity_refs] if node in graph)
    for oid, record in records:
        if oid == current_id or implicated_refs.intersection(record.evidence_refs):
            selected.add(oid)
            selected.update(
                token for token in (record.supplier_token, record.buyer_token, record.bank_token) if token
            )
    refs_by_id = {ref.ref_id: ref for _, record in records for ref in record.evidence}
    refs_by_id.update({ref.ref_id: ref for item in findings for ref in item.evidence})
    edges = []
    for source, target, data in graph.edges(data=True):
        if source not in selected or target not in selected or data["observation_id"] not in selected:
            continue
        refs = [ref for ref in data["evidence_refs"] if ref in refs_by_id]
        if refs:
            edges.append(
                GraphEdge(source=source, target=target, relation=data["edge_type"], evidence_refs=refs)
            )
    for item in findings:
        if (
            item.code
            not in {
                "duplicate_invoice_hash",
                "duplicate_fingerprint",
                "near_duplicate",
                "bank_account_changed",
            }
            or len(item.path) != 2
        ):
            continue
        refs = [ref for ref in item.evidence_refs if ref in refs_by_id]
        if refs and set(item.path) <= selected:
            edges.append(
                GraphEdge(
                    source=item.path[0],
                    target=item.path[1],
                    relation=(
                        "SIMILAR_REFERENCE"
                        if item.code == "near_duplicate"
                        else "BANK_ACCOUNT_CHANGED_CANDIDATE"
                        if item.code == "bank_account_changed"
                        else "DUPLICATE_CANDIDATE"
                    ),
                    evidence_refs=refs,
                )
            )
    used_refs = {ref for edge in edges for ref in edge.evidence_refs}
    return FraudGraph(
        nodes=[GraphNode(node_id=node, **graph.nodes[node]) for node in sorted(selected) if node in graph],
        edges=edges,
        evidence=[refs_by_id[ref] for ref in sorted(used_refs)],
    )
