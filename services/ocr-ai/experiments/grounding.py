"""Disposable OCR-span grounding experiment. Not imported by the live pipeline."""

from __future__ import annotations

import re
import unicodedata

from app.config import GROUNDING_JOIN_GAP, GROUNDING_ROW_OVERLAP, GROUNDING_ROW_TOLERANCE, REVIEW_CONFIDENCE
from app.extract import INSTRUCTION, LABELS, reference_id
from app.ingest import ParsedDocument
from app.normalize import normalize_date, normalize_number


def compact(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def same_row(left, right):
    overlap = max(0, min(left.bbox[3], right.bbox[3]) - max(left.bbox[1], right.bbox[1]))
    height = min(left.bbox[3] - left.bbox[1], right.bbox[3] - right.bbox[1])
    return (
        left.page == right.page
        and left.source == right.source
        and (
            abs(left.bbox[1] - right.bbox[1]) < GROUNDING_ROW_TOLERANCE
            or (height > 0 and overlap / height >= GROUNDING_ROW_OVERLAP)
        )
    )


def segments(parsed):
    rows = []
    for span in sorted(parsed.spans, key=lambda item: (item.page, item.source, item.bbox[1], item.bbox[0])):
        if span.hidden or span.confidence < REVIEW_CONFIDENCE or INSTRUCTION.search(span.text):
            continue
        if rows and same_row(rows[-1][0], span):
            rows[-1].append(span)
        else:
            rows.append([span])
    groups = []
    for row in rows:
        clusters = []
        for span in sorted(row, key=lambda item: item.bbox[0]):
            if clusters and -1 <= span.bbox[0] - clusters[-1][-1].bbox[2] <= GROUNDING_JOIN_GAP:
                clusters[-1].append(span)
            else:
                clusters.append([span])
        groups.extend(clusters)
    return [("".join(item.text for item in group), group) for group in groups]


def grounded_candidate(parsed: ParsedDocument, field: str, candidate: str | None, locale=None) -> dict:
    """Require an explicit role anchor and a unique source observation, not value occurrence."""
    if candidate is None or field not in LABELS:
        return {"status": "unresolved", "reason": "NO_SUPPORTED_CANDIDATE"}

    def normalize(value):
        if field == "amount":
            return normalize_number(value, locale)
        if field in {"issue_date", "due_date"}:
            return normalize_date(value, locale)
        return unicodedata.normalize("NFC", value).strip()

    try:
        wanted = normalize(candidate)
    except (ValueError, ArithmeticError):
        return {"status": "unresolved", "reason": "CANDIDATE_AMBIGUOUS"}
    observations = []
    source_segments = segments(parsed)
    for text, source_spans in source_segments:
        span = source_spans[-1]
        if ":" not in text:
            continue
        anchor, value = text.split(":", 1)
        if compact(anchor) not in {compact(label) for label in LABELS[field]}:
            continue
        source_spans = list(source_spans)
        if not value.strip():
            neighbors = [
                (neighbor_text, neighbor_spans)
                for neighbor_text, neighbor_spans in source_segments
                if same_row(neighbor_spans[0], span) and neighbor_spans[0].bbox[0] >= span.bbox[2]
            ]
            if not neighbors:
                continue
            neighbor_text, neighbor_spans = min(neighbors, key=lambda item: item[1][0].bbox[0])
            # A second label cannot be repurposed as a value.
            if ":" in neighbor_text:
                continue
            value = neighbor_text
            source_spans.extend(neighbor_spans)
        try:
            actual = normalize(value.strip())
        except (ValueError, ArithmeticError):
            continue
        observations.append((actual, source_spans))
    if len(observations) != 1 or observations[0][0] != wanted:
        return {"status": "unresolved", "reason": "NO_UNIQUE_MATCHING_ROLE_EVIDENCE"}
    value, source_spans = observations[0]
    return {
        "status": "grounded",
        "value": str(value),
        "evidence_refs": [reference_id(parsed, span) for span in source_spans],
        "locations": [{"page": span.page, "bbox": span.bbox} for span in source_spans],
    }
