"""Exact, clause-local spans for explicitly optional field requirements.

The caller supplies Domain Pack aliases. These markers waive an obligation;
they neither assert a negative product fact nor infer a field's value.
"""

from __future__ import annotations

import re
from typing import Iterable


def optional_requirement_spans(query: str, aliases: Iterable[str]) -> list[tuple[int, int]]:
    """Locate explicit nonbinding wording without crossing other clauses.

    ``不需要 X`` alone deliberately is not treated as optional here: existing
    contracts distinguish an explicit exclusion from ``没有 X 也可以``.
    No product identity, values, model output or fuzzy matching participate.
    """
    terms = sorted({str(alias) for alias in aliases if str(alias).strip()}, key=lambda term: (-len(term), term))
    if not terms:
        return []
    alias_pattern = "(?:" + "|".join(re.escape(term).replace(r"\ ", r"\s*") for term in terms) + ")"
    field = rf"{alias_pattern}\s*(?:接口|功能|要求)?"
    patterns = (
        rf"(?:没有|不带|无)\s*{field}\s*也\s*(?:可以|行|能接受|没关系)",
        rf"{field}\s*(?:可有可无|不(?:再)?强求|有没有都(?:行|可以)|可以没有|不是必须|并非必须|非必需)",
        rf"(?:不(?:再)?强求)\s*{field}",
    )
    return sorted({match.span() for pattern in patterns for match in re.finditer(pattern, query, re.I)})
