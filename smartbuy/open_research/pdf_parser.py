"""Bounded text extraction for public official PDF/specification attachments."""

from __future__ import annotations

import re
from io import BytesIO

from PyPDF2 import PdfReader

from smartbuy.open_research.models import ExtractedSnippet


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _clean(value: str) -> str:
    return " ".join(value.split())


def parse_pdf(
    content: bytes,
    *,
    target_terms: set[str],
    target_model: str,
    max_pages: int,
    max_snippets: int,
) -> tuple[str | None, list[ExtractedSnippet], int, bool]:
    """Return title, relevant page snippets, scanned pages and model identity.

    The parser never executes embedded content or writes attachments to disk.
    Encrypted/corrupt documents fail by raising the underlying parser error and
    are converted to a sanitized extraction status by the caller.
    """

    reader = PdfReader(BytesIO(content), strict=True)
    if reader.is_encrypted:
        raise ValueError("encrypted_pdf_rejected")
    metadata = reader.metadata or {}
    raw_title = getattr(metadata, "title", None) or metadata.get("/Title")
    title = _clean(str(raw_title))[:500] if raw_title else None
    snippets: list[ExtractedSnippet] = []
    seen: set[str] = set()
    compact_model = _compact(target_model)
    model_confirmed = bool(compact_model and title and compact_model in _compact(title))
    terms = {item.casefold() for item in target_terms if item}
    page_count = min(len(reader.pages), max_pages)
    for page_index in range(page_count):
        page_text = reader.pages[page_index].extract_text() or ""
        if compact_model and compact_model in _compact(page_text):
            model_confirmed = True
        lines = [_clean(item) for item in page_text.splitlines() if _clean(item)]
        for index, line in enumerate(lines):
            window = " | ".join(lines[max(0, index - 1) : min(len(lines), index + 2)])
            folded = window.casefold()
            relevant = bool(compact_model and compact_model in _compact(window)) or any(
                term in folded for term in terms
            )
            if not relevant:
                continue
            clipped = window[:1_000]
            if clipped in seen:
                continue
            seen.add(clipped)
            snippets.append(
                ExtractedSnippet(
                    kind="pdf_text",
                    text=clipped,
                    locator=f"pdf-page[{page_index + 1}]-line[{index}]",
                )
            )
            if len(snippets) >= max_snippets:
                return title, snippets, page_count, model_confirmed
    return title, snippets, page_count, model_confirmed
