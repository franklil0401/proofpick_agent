"""Domain-scoped V2 memory with pack-owned preference allowlists."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any

from smartbuy.domain_packs.loader import LoadedDomainPack


class DomainPreferenceMemoryStore:
    """Persist only explicitly confirmed preferences under a domain-isolated file."""

    def __init__(self, root: Path | str, pack: LoadedDomainPack) -> None:
        self.root = Path(root)
        self.pack = pack
        self.allowed = frozenset(pack.pack.policies["memory"]["allowed_keys"])
        self._lock = RLock()

    def _path(self, user_id: str) -> Path:
        digest = hashlib.sha256(f"{self.pack.domain_id}\x1f{user_id}".encode()).hexdigest()
        return self.root / self.pack.domain_id / f"{digest}.json"

    def _read(self, user_id: str) -> dict[str, Any]:
        path = self._path(user_id)
        if not path.exists():
            return {"enabled": True, "preferences": {}}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {"enabled": True, "preferences": {}}
        if payload.get("domain_id") != self.pack.domain_id:
            return {"enabled": True, "preferences": {}}
        return {
            "enabled": bool(payload.get("enabled", True)),
            "preferences": {
                key: value
                for key, value in payload.get("preferences", {}).items()
                if key in self.allowed
            },
        }

    def _write(self, user_id: str, payload: dict[str, Any]) -> None:
        path = self._path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"version": 1, "domain_id": self.pack.domain_id, **payload},
                ensure_ascii=False,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def recall(self, user_id: str, *, requested: bool) -> dict[str, Any]:
        if not requested:
            return {}
        with self._lock:
            payload = self._read(user_id)
        return dict(payload["preferences"]) if payload["enabled"] else {}

    def upsert(
        self,
        user_id: str,
        preferences: dict[str, Any],
        *,
        explicitly_confirmed: bool,
    ) -> dict[str, Any]:
        if not explicitly_confirmed:
            raise ValueError("long-term preferences require explicit confirmation")
        invalid = sorted(set(preferences) - self.allowed)
        if invalid:
            raise ValueError("preference field is not allowed by the selected Domain Pack")
        with self._lock:
            payload = self._read(user_id)
            payload["preferences"].update(preferences)
            self._write(user_id, payload)
        return self.view(user_id)

    def view(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            return self._read(user_id)

    def delete(self, user_id: str, fields: list[str] | None = None) -> dict[str, Any]:
        with self._lock:
            payload = self._read(user_id)
            if fields is None:
                payload["preferences"] = {}
            else:
                for field in fields:
                    payload["preferences"].pop(field, None)
            self._write(user_id, payload)
        return self.view(user_id)

    def set_enabled(self, user_id: str, enabled: bool) -> dict[str, Any]:
        with self._lock:
            payload = self._read(user_id)
            payload["enabled"] = bool(enabled)
            self._write(user_id, payload)
        return self.view(user_id)
