"""Source-grounded case linkage and explicit unknown issuer authority."""

import json

import pytest
from datagen.financing_case import generate, supporting_pdf


def case_request(client, tmp_path, overrides=None, omit=None, unsupported=False):
    manifest = generate(tmp_path)
    files = []
    entries = []
    for entry in manifest["documents"]:
        kind = entry["document_type"]
        if kind == omit:
            continue
        content = (tmp_path / entry["filename"]).read_bytes()
        if overrides and kind in overrides:
            content = supporting_pdf(kind, overrides=overrides[kind])
        files.append(("files", (entry["filename"], content, "application/pdf")))
        entries.append(
            {**entry, "document_type": "contract" if unsupported and kind == "assignment_notice" else kind}
        )
    manifest["documents"] = entries
    return client.post("/ocr/cases/verify", data={"manifest": json.dumps(manifest)}, files=files)


def test_complete_case_links_but_does_not_prove_authenticity(client, tmp_path):
    response = case_request(client, tmp_path)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["invoice_po"]["status"] == "matched"
    assert len(result["supporting_documents"]) == 10
    assert all(check["status"] == "match" and check["evidence_refs"] for check in result["checks"])
    assert result["declared_balance"]["outstanding"] == "689000.00"
    assert result["review_reasons"] == ["SUPPORTING_DOCUMENT_AUTHENTICITY_UNKNOWN"]
    assert result["review_required"] and not result["financing_authority"]
    assert not result["declared_balance"]["authoritative"]
    assert "100-200-3001" not in response.text


@pytest.mark.parametrize(
    ("kind", "override", "reason"),
    [
        ("goods_receipt", {"Received Quantity": "49000"}, "goods_receipt:SUPPORTING_QUANTITY_MISMATCH"),
        (
            "credit_note",
            {"Invoice Reference": "OTHER-INVOICE"},
            "credit_note:SUPPORTING_REFERENCE_MISMATCH:Invoice Reference",
        ),
        ("buyer_confirmation", {"Acceptance Status": "disputed"}, "BUYER_ACCEPTANCE_UNKNOWN_OR_DISPUTED"),
        ("credit_note", {"Credit Amount": "800000.00"}, "DECLARED_ADJUSTMENTS_EXCEED_INVOICE"),
    ],
)
def test_supporting_discrepancies_never_become_a_clean_case(client, tmp_path, kind, override, reason):
    response = case_request(client, tmp_path, {kind: override})
    assert response.status_code == 200, response.text
    assert reason in response.json()["review_reasons"]
    if "OTHER-INVOICE" in override.values():
        assert response.json()["declared_balance"]["credit_amount"] == "0"


def test_missing_and_unsupported_types_stay_explicit(client, tmp_path):
    response = case_request(client, tmp_path, omit="buyer_confirmation", unsupported=True)
    assert response.status_code == 200, response.text
    assert "MISSING_DOCUMENT:buyer_confirmation" in response.json()["review_reasons"]
    assert "UNSUPPORTED_DOCUMENT_TYPE:contract" in response.json()["review_reasons"]


def test_seed_reproduces_every_byte(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(a, seed=42)
    generate(b, seed=42)
    assert {p.name: p.read_bytes() for p in a.iterdir()} == {p.name: p.read_bytes() for p in b.iterdir()}


def test_duplicate_credit_is_not_deducted_twice(client, tmp_path):
    manifest = generate(tmp_path)
    manifest["documents"] = [
        e for e in manifest["documents"] if e["document_type"] != "insurance_certificate"
    ]
    manifest["documents"].append({"filename": "credit-copy.pdf", "document_type": "credit_note"})
    files = []
    for entry in manifest["documents"]:
        source = "credit_note.pdf" if entry["filename"] == "credit-copy.pdf" else entry["filename"]
        files.append(("files", (entry["filename"], (tmp_path / source).read_bytes(), "application/pdf")))
    response = client.post("/ocr/cases/verify", data={"manifest": json.dumps(manifest)}, files=files)
    assert response.status_code == 200, response.text
    assert "DUPLICATE_SUPPORTING_DOCUMENT_NUMBER:credit_note" in response.json()["review_reasons"]
    assert response.json()["declared_balance"]["credit_amount"] == "10000.00"


def test_unreadable_support_does_not_write_invoice_observation(client, tmp_path):
    manifest = generate(tmp_path)
    (tmp_path / "goods_receipt.pdf").write_bytes(b"%PDF-1.7 invalid")
    files = [
        ("files", (entry["filename"], (tmp_path / entry["filename"]).read_bytes(), "application/pdf"))
        for entry in manifest["documents"]
    ]
    response = client.post("/ocr/cases/verify", data={"manifest": json.dumps(manifest)}, files=files)
    assert response.status_code == 422
    assert not (tmp_path / "state.sqlite").exists()
