"""Repository-external, atomic, TTL-bound storage for open evidence."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from smartbuy.open_research.models import (
    OpenEvidenceRecord,
    TemporaryEvidenceEnvelope,
    TemporaryStoreReadResult,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def scope_token(value: str | None, fallback: str) -> str:
    normalized = (value or fallback).strip() or fallback
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class TemporaryEvidenceStore:
    def __init__(self, root: Path | str, *, enabled: bool = True) -> None:
        self.root = Path(root).resolve()
        self.enabled = enabled
        try:
            self.root.relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("temporary evidence must stay outside the Git workspace")
        if enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _component(value: str) -> str:
        if len(value) != 32 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("evidence scope must be a deterministic opaque token")
        return value

    def _path(
        self,
        user_scope: str,
        session_scope: str,
        thread_scope: str,
        request_scope: str,
    ) -> Path:
        return (
            self.root
            # Keep the hierarchy short enough for default Windows path limits.
            # Full tokens remain in the envelope and are checked again on read.
            / self._component(user_scope)[:16]
            / self._component(session_scope)[:16]
            / self._component(thread_scope)[:16]
            / f"{self._component(request_scope)}.json"
        )

    def write(self, records: list[OpenEvidenceRecord]) -> bool:
        if not self.enabled:
            return False
        if not records:
            raise ValueError("temporary evidence write requires at least one record")
        first = records[0]
        identity = (
            first.user_scope,
            first.session_scope,
            first.thread_scope,
            first.request_scope,
        )
        if any(
            (item.user_scope, item.session_scope, item.thread_scope, item.request_scope)
            != identity
            for item in records
        ):
            raise ValueError("temporary evidence records cross an isolation boundary")
        evidence_ids = [item.evidence_id for item in records]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("duplicate temporary evidence_id")
        path = self._path(*identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = TemporaryEvidenceEnvelope(
            user_scope=first.user_scope,
            session_scope=first.session_scope,
            thread_scope=first.thread_scope,
            request_scope=first.request_scope,
            created_at=min(item.fetched_at for item in records),
            expires_at=min(item.expires_at for item in records),
            records=records,
        )
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(
                    envelope.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return True

    def read(
        self,
        user_scope: str,
        session_scope: str,
        thread_scope: str,
        request_scope: str,
        *,
        now: datetime | None = None,
    ) -> TemporaryStoreReadResult:
        if not self.enabled:
            return TemporaryStoreReadResult(status="disabled", degraded=True)
        path = self._path(user_scope, session_scope, thread_scope, request_scope)
        if not path.is_file():
            return TemporaryStoreReadResult(status="missing")
        try:
            envelope = TemporaryEvidenceEnvelope.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValidationError, ValueError):
            return TemporaryStoreReadResult(
                status="corrupt", degraded=True, error="temporary_evidence_corrupt"
            )
        if (
            envelope.user_scope,
            envelope.session_scope,
            envelope.thread_scope,
            envelope.request_scope,
        ) != (user_scope, session_scope, thread_scope, request_scope):
            return TemporaryStoreReadResult(
                status="corrupt", degraded=True, error="temporary_evidence_scope_mismatch"
            )
        instant = now or datetime.now(UTC)
        if _parse_time(envelope.expires_at) <= instant.astimezone(UTC):
            return TemporaryStoreReadResult(status="expired", degraded=True)
        return TemporaryStoreReadResult(records=envelope.records, status="ok")

    def delete(
        self,
        user_scope: str,
        session_scope: str,
        thread_scope: str,
        request_scope: str,
    ) -> bool:
        if not self.enabled:
            return False
        path = self._path(user_scope, session_scope, thread_scope, request_scope)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def cleanup_expired(self, *, now: datetime | None = None) -> int:
        if not self.enabled or not self.root.is_dir():
            return 0
        instant = now or datetime.now(UTC)
        removed = 0
        for path in self.root.glob("*/*/*/*.json"):
            try:
                envelope = TemporaryEvidenceEnvelope.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, ValidationError, ValueError):
                continue
            if _parse_time(envelope.expires_at) <= instant.astimezone(UTC):
                path.unlink()
                removed += 1
        return removed

    @staticmethod
    def promotion_candidate(records: list[OpenEvidenceRecord]) -> dict[str, Any]:
        """Create a review-only export; it never publishes data or modifies a Pack."""
        return {
            "status": "review_required",
            "auto_publish": False,
            "evidence_scope": "open",
            "record_count": len(records),
            "evidence_ids": [item.evidence_id for item in records],
        }
