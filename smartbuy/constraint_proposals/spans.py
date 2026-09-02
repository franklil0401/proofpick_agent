"""Deterministic exact quote-to-span resolution for LLM constraint proposals."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import SourceSpan


class QuoteSpanStatus(StrEnum):
    RESOLVED = "resolved"
    QUOTE_NOT_FOUND = "quote_not_found"
    OCCURRENCE_REQUIRED = "quote_occurrence_required"
    OCCURRENCE_OUT_OF_RANGE = "quote_occurrence_out_of_range"
    INVALID_QUOTE = "quote_invalid"


@dataclass(frozen=True)
class QuoteSpanResult:
    status: QuoteSpanStatus
    quote: str
    occurrence: int | None
    match_count: int
    span: SourceSpan | None = None

    @property
    def resolved(self) -> bool:
        return self.span is not None and self.status == QuoteSpanStatus.RESOLVED


class QuoteSpanResolver:
    """Resolve exact Python string positions without fuzzy or model-assisted fallback.

    ``occurrence`` is one-based. Overlapping exact matches are counted independently.
    The returned SourceSpan always contains a real slice from ``original_text``.
    """

    def resolve(
        self,
        original_text: str,
        quote: object,
        *,
        occurrence: object = None,
    ) -> QuoteSpanResult:
        if not isinstance(quote, str) or not quote or len(quote) > 300:
            return QuoteSpanResult(
                QuoteSpanStatus.INVALID_QUOTE,
                quote if isinstance(quote, str) else "",
                None,
                0,
            )
        parsed_occurrence: int | None
        if occurrence is None:
            parsed_occurrence = None
        elif isinstance(occurrence, bool):
            return QuoteSpanResult(
                QuoteSpanStatus.OCCURRENCE_OUT_OF_RANGE, quote, None, 0
            )
        else:
            try:
                parsed_occurrence = int(occurrence)
            except (TypeError, ValueError):
                return QuoteSpanResult(
                    QuoteSpanStatus.OCCURRENCE_OUT_OF_RANGE, quote, None, 0
                )
            if parsed_occurrence < 1:
                return QuoteSpanResult(
                    QuoteSpanStatus.OCCURRENCE_OUT_OF_RANGE,
                    quote,
                    parsed_occurrence,
                    0,
                )

        starts: list[int] = []
        cursor = 0
        while cursor <= len(original_text) - len(quote):
            start = original_text.find(quote, cursor)
            if start < 0:
                break
            starts.append(start)
            cursor = start + 1
        if not starts:
            return QuoteSpanResult(
                QuoteSpanStatus.QUOTE_NOT_FOUND, quote, parsed_occurrence, 0
            )
        if parsed_occurrence is None:
            if len(starts) != 1:
                return QuoteSpanResult(
                    QuoteSpanStatus.OCCURRENCE_REQUIRED, quote, None, len(starts)
                )
            selected = starts[0]
        else:
            if parsed_occurrence > len(starts):
                return QuoteSpanResult(
                    QuoteSpanStatus.OCCURRENCE_OUT_OF_RANGE,
                    quote,
                    parsed_occurrence,
                    len(starts),
                )
            selected = starts[parsed_occurrence - 1]
        end = selected + len(quote)
        raw = original_text[selected:end]
        if raw != quote:
            raise AssertionError("exact quote resolution produced a non-identical slice")
        return QuoteSpanResult(
            QuoteSpanStatus.RESOLVED,
            quote,
            parsed_occurrence,
            len(starts),
            SourceSpan(start=selected, end=end, text=raw),
        )
