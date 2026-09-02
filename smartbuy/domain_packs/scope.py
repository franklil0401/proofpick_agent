"""Domain-scoped keys for V2 memory and checkpoint adapters."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from smartbuy.product_packs.loader import ProductPackValidationError


@dataclass(frozen=True)
class DomainExecutionScope:
    domain_id: str
    user_id: str
    session_id: str
    thread_id: str

    def key(self, namespace: str) -> str:
        raw = "\x1f".join(
            (namespace, self.domain_id, self.user_id, self.session_id, self.thread_id)
        )
        return f"{namespace}:{self.domain_id}:{hashlib.sha256(raw.encode()).hexdigest()}"

    def envelope(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"domain_id": self.domain_id, "payload": payload}

    def restore(self, envelope: dict[str, Any]) -> dict[str, Any]:
        if envelope.get("domain_id") != self.domain_id:
            raise ProductPackValidationError("cross-domain state restore is forbidden")
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise ProductPackValidationError("domain state payload is invalid")
        return payload
