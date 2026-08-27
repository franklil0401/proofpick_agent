"""Privacy-bounded memory stores for Stage 4."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any

from smartbuy.domain import AgentState, UserRequirements


DEFAULT_MEMORY_PATH = Path("C:/ai/smartbuy-stage4/preferences.json")
ALLOWED_PREFERENCE_FIELDS = frozenset(
    {
        "budget_min_cny",
        "budget_max_cny",
        "display_size_inch",
        "resolution",
        "min_refresh_rate_hz",
        "exclude_oled",
        "excluded_brands",
        "primary_use",
    }
)


class SessionMemoryStore:
    """Process-local state for follow-up turns; never persisted as product truth."""

    def __init__(self) -> None:
        self._states: dict[str, AgentState] = {}
        self._lock = RLock()

    def get(self, session_id: str) -> AgentState | None:
        with self._lock:
            state = self._states.get(session_id)
            return state.model_copy(deep=True) if state else None

    def save(self, state: AgentState) -> None:
        with self._lock:
            self._states[state.session_id] = state.model_copy(deep=True)

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._states.pop(session_id, None)

    @staticmethod
    def merge_requirements(previous: UserRequirements, current: UserRequirements) -> UserRequirements:
        constraints = {item.field: item for item in previous.hard_constraints}
        constraints.update({item.field: item for item in current.hard_constraints})
        required_fields = list(dict.fromkeys([*previous.required_fields, *current.required_fields, *constraints]))
        return UserRequirements(
            summary=current.summary or previous.summary,
            task_type=current.task_type,
            hard_constraints=list(constraints.values()),
            soft_preferences=current.soft_preferences or previous.soft_preferences,
            required_fields=required_fields,
            excluded_model_ids=list(dict.fromkeys([*previous.excluded_model_ids, *current.excluded_model_ids])),
            pending_questions=current.pending_questions,
        )


class LongTermPreferenceStore:
    """Persistent preferences written only after explicit user confirmation."""

    def __init__(self, path: Path | str = DEFAULT_MEMORY_PATH) -> None:
        self.path = Path(path)
        self._lock = RLock()

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "users": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"version": 1, "users": {}}
        if not isinstance(payload, dict) or not isinstance(payload.get("users"), dict):
            return {"version": 1, "users": {}}
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, self.path)

    def view(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            user = deepcopy(self._read()["users"].get(user_id, {"enabled": True, "preferences": {}}))
        return {
            "enabled": bool(user.get("enabled", True)),
            "preferences": {
                key: value for key, value in user.get("preferences", {}).items() if key in ALLOWED_PREFERENCE_FIELDS
            },
        }

    def upsert(self, user_id: str, preferences: dict[str, Any], *, explicitly_confirmed: bool) -> dict[str, Any]:
        if not explicitly_confirmed:
            raise ValueError("long-term preferences require explicit user confirmation")
        invalid = sorted(set(preferences) - ALLOWED_PREFERENCE_FIELDS)
        if invalid:
            raise ValueError(f"preference field is not allowed: {invalid[0]}")
        with self._lock:
            payload = self._read()
            user = payload["users"].setdefault(user_id, {"enabled": True, "preferences": {}})
            user["preferences"].update(deepcopy(preferences))
            self._write(payload)
        return self.view(user_id)

    def delete(self, user_id: str, fields: list[str] | None = None) -> dict[str, Any]:
        with self._lock:
            payload = self._read()
            if fields is None:
                payload["users"].pop(user_id, None)
            else:
                user = payload["users"].setdefault(user_id, {"enabled": True, "preferences": {}})
                for field in fields:
                    user["preferences"].pop(field, None)
            self._write(payload)
        return self.view(user_id)

    def set_enabled(self, user_id: str, enabled: bool) -> dict[str, Any]:
        with self._lock:
            payload = self._read()
            user = payload["users"].setdefault(user_id, {"enabled": True, "preferences": {}})
            user["enabled"] = bool(enabled)
            self._write(payload)
        return self.view(user_id)

    def recall(self, user_id: str, *, requested: bool) -> dict[str, Any]:
        if not requested:
            return {}
        user = self.view(user_id)
        return user["preferences"] if user["enabled"] else {}
