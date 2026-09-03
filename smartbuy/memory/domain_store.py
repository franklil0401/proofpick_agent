"""Layered, confirmed and domain-isolated V2 preference memory."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from smartbuy.domain_packs.loader import LoadedDomainPack


MEMORY_SCHEMA_VERSION = "proofpick-layered-memory-v1"
_UNSAFE_TEXT = re.compile(
    r"(?:ignore\s+(?:all\s+)?(?:previous\s+)?instructions?|system\s+prompt|"
    r"authorization|api[_ -]?key|绕过.{0,12}checker|忽略.{0,12}指令)",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


class DomainPreferenceMemoryStore:
    """Persist only user-confirmed global/category preferences under hashed identity."""

    _locks_guard = RLock()
    _locks: dict[str, RLock] = {}

    def __init__(self, root: Path | str, pack: LoadedDomainPack) -> None:
        self.root = Path(root)
        self.pack = pack
        policy = pack.pack.policies["memory"]
        self.allowed = frozenset(policy["allowed_keys"])
        self.ranking_allowed = frozenset(policy.get("ranking_allowed_keys", []))
        self.global_allowed = frozenset(policy.get("global_allowed_keys", []))
        self.category_allowed = self.allowed | self.ranking_allowed
        profile = pack.pack.policies["ranking"].get("profile", {})
        self.scenarios = frozenset(
            item.get("scenario_id") for item in profile.get("scenarios", [])
        )
        self.dimensions = frozenset(
            dimension.get("dimension_id")
            for scenario in profile.get("scenarios", [])
            for dimension in scenario.get("dimensions", [])
        )
        lock_key = str(self.root.resolve()).casefold()
        with self._locks_guard:
            self._lock = self._locks.setdefault(lock_key, RLock())

    @staticmethod
    def _identity_digest(user_id: str) -> str:
        if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 128:
            raise ValueError("a bounded user identity is required for long-term memory")
        return hashlib.sha256(user_id.encode("utf-8")).hexdigest()

    def _path(self, user_id: str) -> Path:
        return self.root / "users" / f"{self._identity_digest(user_id)}.json"

    def _legacy_path(self, user_id: str) -> Path:
        digest = hashlib.sha256(f"{self.pack.domain_id}\x1f{user_id}".encode()).hexdigest()
        return self.root / self.pack.domain_id / f"{digest}.json"

    @staticmethod
    def _empty(degraded_reason: str | None = None) -> dict[str, Any]:
        output = {
            "schema_version": MEMORY_SCHEMA_VERSION,
            "enabled": True,
            "global_preferences": {},
            "category_preferences": {},
        }
        if degraded_reason:
            output["degraded_reason"] = degraded_reason
        return output

    def _read(self, user_id: str) -> dict[str, Any]:
        path = self._path(user_id)
        if not path.exists():
            legacy = self._legacy_path(user_id)
            if legacy.exists():
                try:
                    payload = json.loads(legacy.read_text(encoding="utf-8"))
                    if payload.get("domain_id") == self.pack.domain_id:
                        output = self._empty()
                        output["enabled"] = bool(payload.get("enabled", True))
                        for key, value in payload.get("preferences", {}).items():
                            if key in self.allowed:
                                output["category_preferences"].setdefault(
                                    self.pack.domain_id, {}
                                )[key] = self._record(key, value)
                        return output
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                    pass
            return self._empty()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return self._empty("memory_corrupt")
        if payload.get("schema_version") != MEMORY_SCHEMA_VERSION:
            return self._empty("memory_schema_incompatible")
        if not isinstance(payload.get("global_preferences", {}), dict) or not isinstance(
            payload.get("category_preferences", {}), dict
        ):
            return self._empty("memory_corrupt")
        return payload

    def _write(self, user_id: str, payload: dict[str, Any]) -> None:
        path = self._path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _record(
        self,
        key: str,
        value: Any,
        *,
        source: str = "user_confirmed",
        expires_at: str | None = None,
        scope: Literal["global", "category"] = "category",
    ) -> dict[str, Any]:
        return {
            "key": key,
            "value": value,
            "scope": scope,
            "domain_id": self.pack.domain_id if scope == "category" else None,
            "source": source,
            "confirmed_at": _utc_now(),
            "expires_at": expires_at,
            "schema_version": MEMORY_SCHEMA_VERSION,
            "domain_pack_version": self.pack.version if scope == "category" else None,
        }

    def _record_valid(self, record: Any, *, scope: str, now: datetime) -> bool:
        if not isinstance(record, dict):
            return False
        if record.get("schema_version") != MEMORY_SCHEMA_VERSION:
            return False
        if record.get("source") != "user_confirmed":
            return False
        if scope == "category" and record.get("domain_pack_version") != self.pack.version:
            return False
        try:
            expires = _parse_time(record.get("expires_at"))
        except (TypeError, ValueError):
            return False
        return expires is None or expires > now

    @staticmethod
    def _walk_strings(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [text for item in value for text in DomainPreferenceMemoryStore._walk_strings(item)]
        if isinstance(value, dict):
            return [
                text
                for key, item in value.items()
                for text in [str(key), *DomainPreferenceMemoryStore._walk_strings(item)]
            ]
        return []

    def _validate_value(self, key: str, value: Any) -> None:
        if any(_UNSAFE_TEXT.search(text) for text in self._walk_strings(value)):
            raise ValueError("unsafe or instruction-like content cannot enter preference memory")
        if key == "ranking_scenario":
            if not isinstance(value, str) or value not in self.scenarios:
                raise ValueError("ranking scenario is not declared by the Domain Pack")
            return
        if key == "ranking_weights":
            if not isinstance(value, dict) or not set(value) <= self.dimensions:
                raise ValueError("ranking weights reference an unknown profile dimension")
            if any(
                isinstance(item, bool) or not isinstance(item, (int, float)) or item < 0 or item > 1
                for item in value.values()
            ):
                raise ValueError("ranking weights must be numeric values in [0,1]")
            return
        if isinstance(value, dict):
            raise ValueError("structured tool or product payloads cannot enter preference memory")
        if not isinstance(value, (str, int, float, bool, list)) or (
            isinstance(value, list)
            and not all(isinstance(item, (str, int, float, bool)) for item in value)
        ):
            raise ValueError("preference value type is not allowed")

    def recall_with_sources(self, user_id: str | None, *, requested: bool) -> dict[str, Any]:
        if not requested or user_id is None:
            return {
                "enabled": False,
                "preferences": {},
                "global": {},
                "category": {},
                "sources": {},
                "degraded_reasons": [],
            }
        now = datetime.now(UTC)
        with self._lock:
            payload = self._read(user_id)
        if not bool(payload.get("enabled", True)):
            return {
                "enabled": False,
                "preferences": {},
                "global": {},
                "category": {},
                "sources": {},
                "degraded_reasons": [],
            }
        global_values = {
            key: record["value"]
            for key, record in payload.get("global_preferences", {}).items()
            if key in self.global_allowed and self._record_valid(record, scope="global", now=now)
        }
        category_records = payload.get("category_preferences", {}).get(
            self.pack.domain_id, {}
        )
        category_values = {
            key: record["value"]
            for key, record in category_records.items()
            if key in self.category_allowed
            and self._record_valid(record, scope="category", now=now)
        }
        effective = {**global_values, **category_values}
        sources = {key: "global_memory" for key in global_values}
        sources.update({key: "category_memory" for key in category_values})
        return {
            "enabled": True,
            "preferences": effective,
            "global": global_values,
            "category": category_values,
            "sources": sources,
            "degraded_reasons": (
                [str(payload["degraded_reason"])] if payload.get("degraded_reason") else []
            ),
        }

    def recall(self, user_id: str | None, *, requested: bool) -> dict[str, Any]:
        return dict(self.recall_with_sources(user_id, requested=requested)["preferences"])

    def upsert(
        self,
        user_id: str,
        preferences: dict[str, Any],
        *,
        explicitly_confirmed: bool,
        scope: Literal["global", "category"] = "category",
        source: str = "user_confirmed",
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        if not explicitly_confirmed or source != "user_confirmed":
            raise ValueError("long-term preferences require explicit confirmation by the user")
        if expires_at is not None:
            try:
                _parse_time(expires_at)
            except (TypeError, ValueError) as exc:
                raise ValueError("preference expiry is invalid") from exc
        allowed = self.global_allowed if scope == "global" else self.category_allowed
        invalid = sorted(set(preferences) - allowed)
        if invalid:
            raise ValueError("preference field is not allowed by the selected Domain Pack")
        for key, value in preferences.items():
            self._validate_value(key, value)
        with self._lock:
            payload = self._read(user_id)
            if scope == "global":
                target = payload.setdefault("global_preferences", {})
            else:
                target = payload.setdefault("category_preferences", {}).setdefault(
                    self.pack.domain_id, {}
                )
            for key, value in preferences.items():
                target[key] = self._record(
                    key,
                    value,
                    source=source,
                    expires_at=expires_at,
                    scope=scope,
                )
            self._write(user_id, payload)
        return self.view(user_id)

    def view(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            payload = self._read(user_id)
        recalled = self.recall_with_sources(user_id, requested=True)
        now = datetime.now(UTC)
        global_records = payload.get("global_preferences", {})
        category_records = payload.get("category_preferences", {}).get(
            self.pack.domain_id, {}
        )

        def public_record(record: Any, scope: str) -> dict[str, Any]:
            value = dict(record) if isinstance(record, dict) else {}
            value["status"] = (
                "active"
                if self._record_valid(record, scope=scope, now=now)
                else "expired_or_incompatible"
            )
            return value

        return {
            "enabled": bool(payload.get("enabled", True)),
            "preferences": recalled["category"],
            "effective_preferences": recalled["preferences"],
            "global_preferences": recalled["global"],
            "category_preferences": recalled["category"],
            "sources": recalled["sources"],
            "schema_version": MEMORY_SCHEMA_VERSION,
            "domain_id": self.pack.domain_id,
            "domain_pack_version": self.pack.version,
            "records": {
                "global": {
                    key: public_record(record, "global")
                    for key, record in global_records.items()
                    if key in self.global_allowed
                },
                "category": {
                    key: public_record(record, "category")
                    for key, record in category_records.items()
                    if key in self.category_allowed
                },
            },
        }

    def delete(
        self,
        user_id: str,
        fields: list[str] | None = None,
        *,
        scope: Literal["global", "category"] = "category",
    ) -> dict[str, Any]:
        with self._lock:
            payload = self._read(user_id)
            if scope == "global":
                target = payload.setdefault("global_preferences", {})
            else:
                target = payload.setdefault("category_preferences", {}).setdefault(
                    self.pack.domain_id, {}
                )
            if fields is None:
                target.clear()
            else:
                for field in fields:
                    target.pop(field, None)
            self._write(user_id, payload)
        return self.view(user_id)

    def set_enabled(self, user_id: str, enabled: bool) -> dict[str, Any]:
        with self._lock:
            payload = self._read(user_id)
            payload["enabled"] = bool(enabled)
            self._write(user_id, payload)
        return self.view(user_id)
