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


TABLE_HEADER = ("sku", "description", "qty", "unitprice", "linetotal")


def table_rows(spans: list[Span], instruction: re.Pattern):
    """Accept a source row with five whitespace-delimited cells under an exact header.

    This deliberately does not infer missing cells, shifted columns or continuation
    pages. Unknown rows below a detected header invalidate aggregate line sums.
    """
    records, incomplete = [], False
    active = None
    for row in source_rows(spans, instruction):
        text = "  ".join(text for text, _ in segments(row))
        cells = [value.strip() for value in re.split(r"\s{2,}", text.strip())]
        location = (row[0].page, row[0].source)
        if tuple(compact(value) for value in cells) == TABLE_HEADER:
            active = location
            continue
        if active != location:
            continue
        if len(cells) != len(TABLE_HEADER) or any(not value for value in cells):
            incomplete = True
            continue
        # Numeric columns must look numeric; normalization is done by the caller.
        if not all(re.fullmatch(r"[\d.,]+", value) for value in cells[2:]):
            incomplete = True
            continue
        records.append((cells, row))
    if active and not records:
        incomplete = True
    return records, incomplete
