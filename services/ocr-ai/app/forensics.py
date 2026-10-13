"""PDF edit-trace findings: explainable tamper signals, not proof of forgery.

Each signal is a review prompt. Weights are deliberately kept so that even all four
together stay below Policy's 0.30 fraud reject threshold: a heuristic edit trace
should send the invoice to a human, never auto-reject it on its own.
"""

from __future__ import annotations

from app.extract import reference_id
from app.fraud import finding
from app.ingest import ParsedDocument
from app.models import FraudFinding

RULE_VERSION = "pdf-forensics-v1"
SPAN_SIGNALS = {
    "covered": (
        "pdf_text_covered",
        "Printed text is painted over by a later opaque shape (cover-and-retype edit pattern); "
        "the covered text was excluded from extraction",
    ),
    "appended": (
        "pdf_appended_text_layer",
        "Text was drawn by a secondary content stream added after the main page content; "
        "stamps and signatures do this too, so compare against the issuer's original",
    ),
    "font_anomaly": (
        "pdf_font_anomaly",
        "A monetary value uses a font that appears nowhere else in the document",
    ),
}


def forensic_findings(parsed: ParsedDocument) -> list[FraudFinding]:
    findings = []
    for signal, (code, reason) in SPAN_SIGNALS.items():
        spans = [span for span in parsed.spans if signal in span.forensic]
        if spans:
            item = finding(code, reason, [reference_id(parsed, span) for span in spans])
            findings.append(item.model_copy(update={"rule_version": RULE_VERSION}))
    if parsed.incremental_updates:
        item = finding(
            "pdf_incremental_update",
            f"The PDF carries {parsed.incremental_updates} appended revision(s) that redefine page content "
            "after its original save",
        )
        findings.append(item.model_copy(update={"rule_version": RULE_VERSION}))
    return findings
