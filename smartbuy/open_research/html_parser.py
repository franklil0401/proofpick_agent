"""Bounded static-HTML parser that keeps only minimal, field-relevant snippets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from smartbuy.open_research.models import AlternateLink, ExtractedSnippet


_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li"}
_SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}


def _clean(value: str) -> str:
    return " ".join(value.split())


def _relevant(text: str, terms: set[str], model: str) -> bool:
    folded = text.casefold()
    compact_model = re.sub(r"[^a-z0-9]", "", model.casefold())
    compact_text = re.sub(r"[^a-z0-9]", "", folded)
    return bool(compact_model and compact_model in compact_text) or any(
        term.casefold() in folded for term in terms if term
    )


@dataclass(frozen=True)
class ParsedHTML:
    title: str | None
    language: str | None
    canonical_url: str | None
    alternate_links: list[AlternateLink]
    snippets: list[ExtractedSnippet]
    visible_text_length: int
    script_count: int


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.language: str | None = None
        self.canonical: str | None = None
        self.alternates: list[tuple[str, str | None]] = []
        self.stack: list[str] = []
        self.skip_depth = 0
        self.script_count = 0
        self.json_ld_depth = 0
        self.json_ld_parts: list[str] = []
        self.json_ld_documents: list[str] = []
        self.block_tag: str | None = None
        self.block_parts: list[str] = []
        self.blocks: list[tuple[str, str]] = []
        self.row_cells: list[str] | None = None
        self.cell_parts: list[str] | None = None
        self.rows: list[list[str]] = []
        self.dt_parts: list[str] | None = None
        self.dd_parts: list[str] | None = None
        self.definition_pairs: list[tuple[str, str]] = []
        self.last_dt: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        attributes = {key.casefold(): value for key, value in attrs}
        self.stack.append(tag)
        if tag == "html":
            self.language = attributes.get("lang") or self.language
        if tag == "link":
            rel = (attributes.get("rel") or "").casefold().split()
            href = attributes.get("href")
            if href and "canonical" in rel:
                self.canonical = href
            if href and "alternate" in rel:
                self.alternates.append((href, attributes.get("hreflang")))
        if tag == "script":
            self.script_count += 1
            if (attributes.get("type") or "").casefold() == "application/ld+json":
                self.json_ld_depth += 1
                self.json_ld_parts = []
            else:
                self.skip_depth += 1
            return
        if tag in _SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in _BLOCK_TAGS and self.block_tag is None:
            self.block_tag = tag
            self.block_parts = []
        if tag == "tr":
            self.row_cells = []
        if tag in {"th", "td"} and self.row_cells is not None:
            self.cell_parts = []
        if tag == "dt":
            self.dt_parts = []
        if tag == "dd":
            self.dd_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "script" and self.json_ld_depth:
            self.json_ld_depth -= 1
            document = _clean(" ".join(self.json_ld_parts))
            if document:
                self.json_ld_documents.append(document[:200_000])
            self.json_ld_parts = []
        elif tag in _SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth:
            if tag == self.block_tag:
                text = _clean(" ".join(self.block_parts))
                if text:
                    self.blocks.append((tag, text[:2_000]))
                self.block_tag = None
                self.block_parts = []
            if tag in {"th", "td"} and self.cell_parts is not None:
                text = _clean(" ".join(self.cell_parts))
                if text and self.row_cells is not None:
                    self.row_cells.append(text[:1_000])
                self.cell_parts = None
            if tag == "tr" and self.row_cells is not None:
                if self.row_cells:
                    self.rows.append(self.row_cells[:12])
                self.row_cells = None
            if tag == "dt" and self.dt_parts is not None:
                self.last_dt = _clean(" ".join(self.dt_parts))[:500] or None
                self.dt_parts = None
            if tag == "dd" and self.dd_parts is not None:
                value = _clean(" ".join(self.dd_parts))[:1_000]
                if self.last_dt and value:
                    self.definition_pairs.append((self.last_dt, value))
                self.dd_parts = None
        if self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self.json_ld_depth:
            self.json_ld_parts.append(data)
            return
        if self.skip_depth:
            return
        text = _clean(data)
        if not text:
            return
        if self.stack and self.stack[-1] == "title":
            self.title_parts.append(text)
        if self.block_tag is not None:
            self.block_parts.append(text)
        if self.cell_parts is not None:
            self.cell_parts.append(text)
        if self.dt_parts is not None:
            self.dt_parts.append(text)
        if self.dd_parts is not None:
            self.dd_parts.append(text)


def _walk_json(value: Any, path: str = "jsonld") -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    if isinstance(value, dict):
        name = value.get("name") or value.get("propertyID")
        raw = value.get("value")
        if name is not None and raw is not None and not isinstance(raw, (dict, list)):
            output.append((path, f"{name}: {raw}"))
        for key, item in value.items():
            if key in {"description", "name", "model", "sku"} and isinstance(item, str):
                output.append((f"{path}.{key}", f"{key}: {item}"))
            if isinstance(item, (dict, list)):
                output.extend(_walk_json(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value[:100]):
            output.extend(_walk_json(item, f"{path}[{index}]"))
    return output


def parse_html(
    html_text: str,
    *,
    base_url: str,
    target_terms: set[str],
    target_model: str,
    max_snippets: int,
) -> ParsedHTML:
    parser = _Parser()
    parser.feed(html_text)
    snippets: list[ExtractedSnippet] = []
    seen: set[str] = set()

    def add(kind: str, text: str, locator: str) -> None:
        cleaned = _clean(text)[:1_000]
        if not cleaned or cleaned in seen or len(snippets) >= max_snippets:
            return
        if not _relevant(cleaned, target_terms, target_model):
            return
        seen.add(cleaned)
        snippets.append(ExtractedSnippet(kind=kind, text=cleaned, locator=locator[:300]))

    for document_index, document in enumerate(parser.json_ld_documents[:20]):
        try:
            payload = json.loads(document)
        except (json.JSONDecodeError, TypeError):
            continue
        for locator, text in _walk_json(payload, f"jsonld[{document_index}]"):
            add("json_ld", text, locator)

    for index, row in enumerate(parser.rows[:1_000]):
        add("specification", " | ".join(row), f"table-row[{index}]")
    for index, (name, value) in enumerate(parser.definition_pairs[:1_000]):
        add("specification", f"{name} | {value}", f"definition-list[{index}]")
    previous = ""
    target_context = ""
    context_blocks_remaining = 0
    compact_target = re.sub(r"[^a-z0-9]", "", target_model.casefold())
    for index, (tag, text) in enumerate(parser.blocks[:5_000]):
        combined = f"{previous} | {text}" if previous and len(text) < 800 else text
        compact_text = re.sub(r"[^a-z0-9]", "", text.casefold())
        if compact_target and compact_target in compact_text:
            target_context = text[:300]
            context_blocks_remaining = 8
        elif target_context and context_blocks_remaining > 0:
            combined = f"{target_context} | {combined}"
            context_blocks_remaining -= 1
        add("visible_text", combined, f"{tag}[{index}]")
        previous = text

    alternates: list[AlternateLink] = []
    for href, hreflang in parser.alternates[:50]:
        absolute = urljoin(base_url, href)
        item = AlternateLink(url=absolute, hreflang=hreflang)
        if item not in alternates:
            alternates.append(item)
        if len(alternates) >= 30:
            break
    title = _clean(" ".join(parser.title_parts))[:500] or None
    visible_length = sum(len(text) for _, text in parser.blocks)
    return ParsedHTML(
        title=title,
        language=(parser.language[:32] if parser.language else None),
        canonical_url=(urljoin(base_url, parser.canonical) if parser.canonical else None),
        alternate_links=alternates,
        snippets=snippets,
        visible_text_length=visible_length,
        script_count=parser.script_count,
    )
