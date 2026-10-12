"""Source geometry and explicit role anchors; model candidates cannot assign fields."""

from __future__ import annotations

import re
import unicodedata

from app.config import GROUNDING_JOIN_GAP, GROUNDING_ROW_OVERLAP, GROUNDING_ROW_TOLERANCE
from app.ingest import Span


def compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def same_row(left: Span, right: Span) -> bool:
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


def source_rows(spans: list[Span], instruction: re.Pattern) -> list[list[Span]]:
    rows: list[list[Span]] = []
    for span in sorted(spans, key=lambda item: (item.page, item.source, item.bbox[1], item.bbox[0])):
        if (
            span.hidden
            or instruction.search(span.text)
            or any(unicodedata.category(char) == "Cf" for char in span.text)
        ):
            continue
        if rows and same_row(rows[-1][0], span):
            rows[-1].append(span)
        else:
            rows.append([span])
    return [sorted(row, key=lambda item: item.bbox[0]) for row in rows]


def segments(row: list[Span]) -> list[tuple[str, list[Span]]]:
    groups: list[list[Span]] = []
    for span in row:
        if groups and -1 <= span.bbox[0] - groups[-1][-1].bbox[2] <= GROUNDING_JOIN_GAP:
            groups[-1].append(span)
        else:
            groups.append([span])
    return [("".join(span.text for span in group), group) for group in groups]


def anchored_rows(spans: list[Span], instruction: re.Pattern) -> list[tuple[str, list[Span]]]:
    """Separate panels; join a blank anchor to its immediate same-row value only.

    Fullwidth punctuation is normalized solely to find the label delimiter; values
    retain their observed characters. A second colon remains in the value so the
    extractor rejects ambiguous boundaries rather than swallowing another label.
    """
    result = []
    for row in source_rows(spans, instruction):
        pieces = segments(row)
        for index, (text, source) in enumerate(pieces):
            text = text.replace("：", ":")
            if ":" not in text:
                continue
            anchor, value = text.split(":", 1)
            refs = list(source)
            if not value.strip() and index + 1 < len(pieces):
                neighbor, neighbor_spans = pieces[index + 1]
                if ":" not in neighbor.replace("：", ":"):
                    value = neighbor
                    refs.extend(neighbor_spans)
            if value.strip():
                result.append((anchor.strip() + ": " + value.strip(), refs))
    return result


TABLE_HEADERS = {
    ("sku", "description", "qty", "unitprice", "linetotal"),
    ("sku", "description", "qty", "unit", "price", "total"),
}

TABLE_SUMMARY = re.compile(
    r"^(subtotal|sub-total|tax(?:\s+amount)?|vat(?:\s+amount)?|vat\s+\d+(?:\.\d+)?%?|"
    r"grand\s+total|total|amount\s+due|balance\s+due|discount|freight|shipping|duty)(?:\b|$)",
    re.IGNORECASE,
)


def _unsupported_table_header(cells: list[str]) -> bool:
    """Recognize table-shaped headers that are too different to parse safely."""
    normalized = {compact(cell) for cell in cells}
    has_sku = bool(normalized & {"sku", "itemcode", "productcode"})
    has_description = bool(normalized & {"description", "itemdescription", "productdescription"})
    has_quantity = bool(normalized & {"qty", "quantity", "orderedqty"})
    has_money = bool(normalized & {"unitprice", "price", "linetotal", "total", "amount"})
    return has_sku and has_description and has_quantity and has_money


def table_rows(spans: list[Span], instruction: re.Pattern):
    """Accept five- or six-column source rows under exact supported headers.

    This deliberately does not infer missing cells, shifted columns or continuation
    pages. Unknown rows inside an active table invalidate aggregate line sums. A
    recognized financial-summary row closes the table before it is interpreted.
    """
    records, incomplete = [], False
    active = None
    for row in source_rows(spans, instruction):
        text = "  ".join(text for text, _ in segments(row))
        cells = [value.strip() for value in re.split(r"\s{2,}", text.strip())]
        location = (row[0].page, row[0].source)
        normalized_header = tuple(compact(value) for value in cells)
        if normalized_header in TABLE_HEADERS:
            if active and len(records) == active[2]:
                incomplete = True
            active = (location, len(cells), len(records))
            continue
        if _unsupported_table_header(cells):
            incomplete = True
            active = None
            continue
        if active is None or active[0] != location:
            continue
        if cells and TABLE_SUMMARY.match(cells[0]):
            if len(records) == active[2]:
                incomplete = True
            active = None
            continue
        expected_cells = active[1]
        if len(cells) != expected_cells or any(not value for value in cells):
            incomplete = True
            continue
        # Numeric columns must look numeric; normalization is done by the caller.
        numeric_cells = cells[2:] if expected_cells == 5 else (cells[2], cells[4], cells[5])
        if not all(re.fullmatch(r"[\d.,]+", value) for value in numeric_cells):
            incomplete = True
            continue
        records.append((cells, row))
    if active and len(records) == active[2]:
        incomplete = True
    return records, incomplete
