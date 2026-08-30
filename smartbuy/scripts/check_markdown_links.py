"""Check local links in the repository's maintained Markdown documents."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ROOT_DOCUMENTS = (
    "README.md",
    "THIRD_PARTY_NOTICES.md",
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
EXTERNAL_SCHEMES = {"data", "http", "https", "mailto", "tel"}


def _documents() -> list[Path]:
    documents = [REPOSITORY_ROOT / item for item in ROOT_DOCUMENTS]
    documents.extend(sorted((REPOSITORY_ROOT / "smartbuy" / "docs").rglob("*.md")))
    return documents


def _local_target(raw_destination: str) -> str | None:
    destination = raw_destination.strip()
    if destination.startswith("<") and destination.endswith(">"):
        destination = destination[1:-1].strip()
    elif " " in destination:
        destination = destination.split(" ", 1)[0]

    if not destination or destination.startswith("#"):
        return None

    parsed = urlsplit(destination)
    if parsed.scheme.lower() in EXTERNAL_SCHEMES or parsed.netloc:
        return None
    target = unquote(parsed.path)
    return target or None


def check_links() -> tuple[int, list[str]]:
    checked_links = 0
    failures: list[str] = []
    for document in _documents():
        if not document.is_file():
            failures.append(f"missing maintained document: {document.relative_to(REPOSITORY_ROOT)}")
            continue
        text = document.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in MARKDOWN_LINK.finditer(line):
                target = _local_target(match.group(1))
                if target is None:
                    continue
                checked_links += 1
                candidate = (document.parent / target).resolve()
                if not candidate.exists():
                    relative_document = document.relative_to(REPOSITORY_ROOT)
                    failures.append(f"{relative_document}:{line_number}: missing {target}")
    return checked_links, failures


def main() -> int:
    checked_links, failures = check_links()
    if failures:
        print("Local Markdown link check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"Local Markdown links OK: {checked_links} links across {len(_documents())} documents")
    return 0


if __name__ == "__main__":
    sys.exit(main())
