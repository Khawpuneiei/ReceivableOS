"""Behavioral checks through real multipart uploads, with ephemeral observation state."""

import json
from pathlib import Path

import pytest
from datagen.generate import document_lines, render_pdf
from datagen.showcase_invoices import SHOWCASE_PROFILES, build_pdf

from app.extract import extract_document
from app.history import ObservationStore
from app.ingest import run_worker
from app.qwen import VisionCandidates
from shared.schemas import ExtractedInvoice

DATA = Path(__file__).resolve().parents[3] / "data" / "invoices"
RELIABILITY_DATA = DATA / "reliability"


def upload(client, content, headers=None):
    return client.post(
        "/ocr/extract", files={"file": ("../../untrusted.pdf", content, "application/pdf")}, headers=headers
    )


@pytest.mark.parametrize(
    ("filename", "profile_index"),
    [("northstar_invoice.pdf", 0), ("bluepeak_invoice.pdf", 1)],
)
def test_showcase_invoice_layouts_extract_all_fields_and_lines(client, filename, profile_index):
    showcase = DATA / "showcase"
    content = (showcase / filename).read_bytes()
    profile = SHOWCASE_PROFILES[profile_index]
    response = upload(client, content)
    assert response.status_code == 200, response.text
    value = response.json()

    assert value["invoice_no"] == profile["invoice_no"]
    assert value["amount"] == profile["total"]
    assert value["currency"] == "USD"
    assert value["supplier"]["name"] == profile["supplier"]
    assert value["buyer"]["name"] == profile["buyer"]
    assert len(value["line_items"]) == 2
    assert value["validation_flags"] == ["LEGACY_FINGERPRINT_SCOPE_REQUIRES_REVIEW"]
    assert value["fraud_flags"] == []
    assert value["review_required"] is True


@pytest.mark.parametrize("profile", SHOWCASE_PROFILES, ids=("northstar", "bluepeak"))
def test_showcase_invoice_and_po_fields_match_under_global_review_guard(client, profile):
    invoice = (DATA / "showcase" / f"{profile['style']}_invoice.pdf").read_bytes()
    purchase_order = build_pdf(profile, kind="purchase_order")
    response = client.post(
        "/ocr/verify",
        files={
            "invoice_file": ("invoice.pdf", invoice, "application/pdf"),
            "po_file": ("purchase-order.pdf", purchase_order, "application/pdf"),
        },
    )
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["status"] == "review"
    assert value["review_reasons"] == ["LEGACY_FINGERPRINT_SCOPE_REQUIRES_REVIEW"]
    assert value["invoice"]["document_number"]["value"] == profile["invoice_no"]
    assert value["invoice"]["amount"]["value"] == profile["total"]
    assert all(check["status"] == "match" for check in value["checks"])


def pair(client, name, language="en"):
    return client.post(
        "/ocr/verify",
        files={
            "invoice_file": (
                "invoice.pdf",
                (DATA / f"{language}_invoice_{name}.pdf").read_bytes(),
                "application/pdf",
            ),
            "po_file": ("po.pdf", (DATA / f"{language}_po_clean.pdf").read_bytes(), "application/pdf"),
        },
    )


@pytest.mark.parametrize("language", ["en", "th"])
def test_actual_pdf_extract_and_shared_compatibility(client, language):
    response = upload(client, (DATA / f"{language}_invoice_clean.pdf").read_bytes())
    assert response.status_code == 200, response.text
    value = response.json()
    shared = ExtractedInvoice.model_validate(value)
    assert str(shared.amount) == "749000.00"
    assert shared.invoice_no == "SFP-INV-2026-0142"
    assert value["fraud_score"] == 0 and not value["review_required"]
    assert "100-200-3001" not in response.text and "1002003001" not in response.text
    doc = value["document_evidence"]
    refs = {r["ref_id"] for r in doc["evidence"]}
    for field in ("document_number", "amount", "currency", "issue_date", "due_date"):
        assert set(doc[field]["evidence_refs"]) <= refs
        assert doc[field]["evidence_refs"]
    assert all(r["page"] == 1 and r["bbox"] for r in doc["evidence"])
    changed = upload(client, render_pdf(document_lines(invoice_no="NEW-91", total="800000.00"))).json()
    assert changed["invoice_no"] == "NEW-91" and changed["amount"] == "800000.00"
    assert changed["doc_hash"] != value["doc_hash"]
    assert "math_inconsistent" in changed["fraud_flags"]


def test_chinese_invoice_extraction_is_grounded_and_review_only(client):
    response = upload(client, (RELIABILITY_DATA / "invoice-zh-stacked-0.pdf").read_bytes())
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["invoice_no"] == "INV-ZH-STACKED-0"
    assert value["amount"] == "79.18" and value["currency"] == "CNY"
    assert value["issue_date"] == "2026-10-01" and value["due_date"] == "2026-11-15"
    assert value["supplier"]["name"] == "示例包装有限公司"
    assert value["buyer"]["name"] == "示例零售有限公司"
    assert len(value["document_evidence"]["lines"]) == 2
    assert value["review_required"]
    assert "EXPERIMENTAL_CHINESE_REQUIRES_REVIEW" in value["validation_flags"]
    assert all(
        field["status"] == "present" and field["evidence_refs"]
        for field in (
            value["document_evidence"]["document_number"],
            value["document_evidence"]["amount"],
            value["document_evidence"]["currency"],
            value["document_evidence"]["supplier"]["name"],
            value["document_evidence"]["buyer"]["name"],
        )
    )


def test_chinese_invoice_po_pair_keeps_unitless_line_checks_unknown(client):
    response = client.post(
        "/ocr/verify",
        files={
            "invoice_file": (
                "invoice.pdf",
                (RELIABILITY_DATA / "invoice-zh-stacked-0.pdf").read_bytes(),
                "application/pdf",
            ),
            "po_file": (
                "po.pdf",
                (RELIABILITY_DATA / "purchase_order-zh-stacked-0.pdf").read_bytes(),
                "application/pdf",
            ),
        },
    )
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["status"] == "review"
    assert "EXPERIMENTAL_CHINESE_REQUIRES_REVIEW" in value["review_reasons"]
    assert value["invoice"]["amount"]["value"] == value["purchase_order"]["amount"]["value"]
    checks = {check["field"]: check for check in value["checks"]}
    assert checks["line_items.PACK-A.unit"]["status"] == "unknown"
    assert checks["line_items.PACK-A.quantity"]["status"] == "unknown"
    assert checks["line_items.PACK-A.unit_price"]["status"] == "unknown"


@pytest.mark.parametrize(
    "marker",
    ["REVISED INVOICE — supersedes the prior invoice", "CREDIT NOTE"],
)
def test_revision_label_requires_human_review(client, marker):
    lines = document_lines(invoice_no="REV-2026-0001")
    lines.append(marker)
    response = upload(client, render_pdf(lines))
    assert response.status_code == 200, response.text
    value = response.json()
    assert "REVISION_OR_CREDIT_NOTE_REQUIRES_REVIEW" in value["validation_flags"]
    assert value["review_required"]


def test_chinese_red_letter_invoice_marker_requires_review():
    parsed = run_worker("parse", (RELIABILITY_DATA / "invoice-zh-stacked-0.pdf").read_bytes())
    marker = parsed.spans[0].model_copy(update={"text": "红字发票", "ordinal": len(parsed.spans) + 1})
    parsed = parsed.model_copy(update={"spans": [*parsed.spans, marker]})
    extraction = extract_document(parsed, "invoice")
    assert "REVISION_OR_CREDIT_NOTE_REQUIRES_REVIEW" in extraction.document.review_reasons


def test_same_reference_amount_revision_is_a_near_duplicate_review(client):
    original = document_lines(invoice_no="REV-2026-0002")
    revised = [
        line.replace("14.00 | 700000.00", "14.20 | 710000.00")
        .replace("Subtotal: 700000.00", "Subtotal: 710000.00")
        .replace("Tax: 49000.00", "Tax: 49700.00")
        .replace("Total: 749000.00", "Total: 759700.00")
        for line in original
    ]
    first = upload(client, render_pdf(original)).json()
    second = upload(client, render_pdf(revised)).json()
    assert second["amount"] == "759700.00"
    assert first["doc_hash"] != second["doc_hash"]
    assert "near_duplicate" in second["fraud_flags"]
    assert second["review_required"]
    assert "math_inconsistent" not in second["fraud_flags"]


def test_same_supplier_bank_token_change_requires_review_without_leaking_account(client):
    first_lines = document_lines(invoice_no="BANK-CHANGE-2026-01")
    second_lines = [
        line.replace("100-200-3001", "900-800-7002")
        for line in document_lines(invoice_no="BANK-CHANGE-2026-02")
    ]
    first = upload(client, render_pdf(first_lines)).json()
    second_response = upload(client, render_pdf(second_lines))
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    assert first["fraud_flags"] == []
    assert "bank_account_changed" in second["fraud_flags"]
    assert second["review_required"]
    assert "100-200-3001" not in second_response.text
    assert "900-800-7002" not in second_response.text
    finding = next(item for item in second["fraud_details"] if item["code"] == "bank_account_changed")
    assert len(finding["path"]) == 2 and len(finding["evidence_refs"]) >= 2
    assert finding["rule_version"] == "graph-rules-v2"
    assert second["fraud_graph"]["schema_version"] == "ocr-graph-v2"
    assert second["handoff"]["graph_rule_version"] == "graph-rules-v2"
    assert any(
        edge["relation"] == "BANK_ACCOUNT_CHANGED_CANDIDATE" for edge in second["fraud_graph"]["edges"]
    )


@pytest.mark.parametrize("language", ["en", "th"])
def test_independent_pair_provenance(client, language):
    response = pair(client, "clean", language)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "matched"
    assert data["invoice"]["doc_hash"] != data["purchase_order"]["doc_hash"]
    invoice_refs = {r["ref_id"] for r in data["invoice"]["evidence"]}
    po_refs = {r["ref_id"] for r in data["purchase_order"]["evidence"]}
    for check in data["checks"]:
        assert check["status"] == "match"
        assert check["invoice_evidence_refs"] and check["po_evidence_refs"]
        assert set(check["invoice_evidence_refs"]) <= invoice_refs
        assert set(check["po_evidence_refs"]) <= po_refs
    assert {"po_reference", "supplier.identity", "buyer.identity", "currency", "tax_basis", "amount"} <= {
        c["field"] for c in data["checks"]
    }


@pytest.mark.parametrize(
    "case, status, code",
    [
        ("amount_mismatch", "mismatch", "po_amount_mismatch"),
        ("currency_mismatch", "mismatch", "po_currency_mismatch"),
        ("incomplete", "review", None),
        ("partial", "review", None),
    ],
)
def test_pair_mismatch_and_unknown(client, case, status, code):
    data = pair(client, case).json()
    assert data["status"] == status
    if code:
        assert code in {f["code"] for f in data["fraud_details"]}
    if case == "currency_mismatch":
        assert next(c for c in data["checks"] if c["field"] == "amount")["status"] == "unknown"
    if case == "incomplete":
        assert data["compatible_invoice"] is None
        assert data["invoice"]["due_date"]["value"] is None
        assert upload(client, (DATA / "en_invoice_incomplete.pdf").read_bytes()).status_code == 422
    if case == "partial":
        assert any(c["rule_code"] == "PARTIAL_ALLOCATION_EVIDENCE_REQUIRED" for c in data["checks"])


def test_duplicate_bytes_semantics_retry_and_persistence(client, monkeypatch):
    content = (DATA / "en_invoice_clean.pdf").read_bytes()
    first = upload(client, content, {"Idempotency-Key": "one"}).json()
    retry = upload(client, content, {"Idempotency-Key": "one"}).json()
    assert first["invoice_id"] == retry["invoice_id"] and not retry["fraud_flags"]
    second = upload(client, content).json()
    assert {"duplicate_invoice_hash", "duplicate_fingerprint"} <= set(second["fraud_flags"])
    rerender = upload(client, (DATA / "en_invoice_duplicate_render.pdf").read_bytes()).json()
    assert "duplicate_fingerprint" in rerender["fraud_flags"]
    assert "duplicate_invoice_hash" not in rerender["fraud_flags"]
    assert first["semantic_fingerprint"] == rerender["semantic_fingerprint"]
    assert (
        upload(client, render_pdf(document_lines(invoice_no="OTHER")), {"Idempotency-Key": "one"}).status_code
        == 409
    )
    import os

    store = ObservationStore(Path(os.environ["OCR_STATE_PATH"]))
    assert len(store.observations()) == 3
    payload = json.dumps([v.model_dump(mode="json") for _, v in store.observations()])
    assert "100-200-3001" not in payload and "1002003001" not in payload
    assert store.path.stat().st_mode & 0o777 == 0o600
    monkeypatch.delenv("FINGERPRINT_HMAC_KEY")
    assert upload(client, content).status_code == 503


@pytest.mark.parametrize(
    "case, flagged", [("visible_injection", True), ("hidden_injection", True), ("benign_note", False)]
)
def test_injected_twins_preserve_fields_and_have_no_authority(client, case, flagged):
    data = upload(client, (DATA / f"en_invoice_{case}.pdf").read_bytes()).json()
    assert data["invoice_no"] == "SFP-INV-2026-0142" and data["amount"] == "749000.00"
    assert bool(data["injection_flags"]) is flagged
    assert data["fraud_score"] == 0
    assert data["review_required"] is flagged


def test_unicode_names_and_unknown_jurisdiction(client):
    font = DATA / "fonts" / "NotoSansThai-Regular.ttf"
    content = render_pdf(document_lines(supplier="บริษัท สยาม"), font_path=font)
    value = upload(client, content).json()
    assert value["supplier"]["name"] == "บริษัท สยาม"
    lines = document_lines(supplier_id="DE-AB-99")
    lines = [
        line.replace("Supplier Country: TH", "Supplier Country: DE").replace(
            "Supplier ID Scheme: TAX_ID", "Supplier ID Scheme: VAT"
        )
        for line in lines
    ]
    result = upload(client, render_pdf(lines)).json()
    assert not any(f.startswith("TAX_ID_INVALID:supplier") for f in result["validation_flags"])
    assert "LEGACY_FINGERPRINT_SCOPE_REQUIRES_REVIEW" in result["validation_flags"]


def test_qwen_candidates_cannot_replace_grounded_values(client, monkeypatch):
    monkeypatch.setenv("OCR_QWEN_ENABLED", "1")
    monkeypatch.setattr(
        "app.pipeline.read_candidates",
        lambda *_: VisionCandidates(
            **{
                name: False if name == "instructions_found" else "1.00" if name == "amount" else None
                for name in VisionCandidates.model_fields
            }
        ),
    )
    value = upload(client, (DATA / "en_invoice_clean.pdf").read_bytes()).json()
    assert value["amount"] == "749000.00"
    assert "QWEN_DISAGREEMENT:amount" in value["validation_flags"]
    monkeypatch.setattr("app.pipeline.read_candidates", lambda *_: None)
    value = upload(client, render_pdf(document_lines(invoice_no="Q-92"))).json()
    assert "QWEN_UNAVAILABLE_OR_INVALID" in value["validation_flags"]


def test_account_cannot_leak_through_other_fields(client):
    lines = document_lines(supplier="Pay 100-200-3001 now")
    response = upload(client, render_pdf(lines))
    assert response.status_code == 422
    assert "100-200-3001" not in response.text


def test_raw_bank_secret_required_only_for_scoped_account(client, monkeypatch):
    monkeypatch.delenv("BANK_TOKEN_HMAC_KEY")
    assert upload(client, (DATA / "en_invoice_clean.pdf").read_bytes()).status_code == 503


def test_invalid_key_returns_safe_error(client):
    assert (
        upload(
            client, (DATA / "en_invoice_clean.pdf").read_bytes(), {"Idempotency-Key": "x" * 201}
        ).status_code
        == 422
    )


@pytest.mark.parametrize("language", ["en", "th"])
def test_graph_explanations_from_actual_uploads(client, language, monkeypatch, tmp_path):
    clean = upload(client, (DATA / f"{language}_invoice_clean.pdf").read_bytes()).json()
    shared = upload(client, (DATA / f"{language}_invoice_shared_account.pdf").read_bytes()).json()
    assert not clean["fraud_flags"]
    assert shared["fraud_flags"] == ["shared_bank_token"]
    assert shared["fraud_score"] == 0.15 and shared["review_required"]
    finding = shared["fraud_details"][0]
    assert len(finding["path"]) == 5 and finding["evidence_refs"]
    assert all("100-200-3001" not in node for node in finding["path"])
    monkeypatch.setenv("OCR_STATE_PATH", str(tmp_path / "cluster.sqlite"))
    first = pair(client, "cluster_math", language).json()
    second = pair(client, "cluster_currency", language).json()
    assert "suspicious_cluster" not in {f["code"] for f in first["fraud_details"]}
    assert {"shared_bank_token", "suspicious_cluster"} <= {f["code"] for f in second["fraud_details"]}


def test_fraud_evidence_locations_resolve_both_current_and_prior_sources(client):
    first = upload(client, (DATA / "en_invoice_clean.pdf").read_bytes()).json()
    second = upload(client, (DATA / "en_invoice_duplicate_render.pdf").read_bytes()).json()
    finding = next(f for f in second["fraud_details"] if f["code"] == "duplicate_fingerprint")
    assert {ref["doc_hash"] for ref in finding["evidence"]} == {first["doc_hash"], second["doc_hash"]}
    assert set(finding["evidence_refs"]) == {ref["ref_id"] for ref in finding["evidence"]}


def test_line_unknown_is_review_and_bank_scope_is_not_inferred(client):
    lines = [
        line.replace("700000.00", "unknown") if line.startswith("Item:") else line
        for line in document_lines()
    ]
    response = upload(client, render_pdf(lines))
    assert response.status_code == 200
    assert "LINE_EVIDENCE_UNRESOLVED:0" in response.json()["validation_flags"]
    lines = [line for line in document_lines() if not line.startswith("Bank Country:")]
    data = upload(client, render_pdf(lines)).json()
    assert "BANK_SCOPE_UNKNOWN" in data["validation_flags"]
