"""Bounded cache with hashed keys, TTL, integrity checks and fail-open reads.

The cache is deliberately opt-in. Callers must declare that a payload belongs
to the public evaluation corpus; arbitrary user prompts are not cached by
default. Cache files are runtime data and live outside the repository.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any


ALLOWED_OPERATIONS = frozenset(
    {"query_embedding", "vector_recall", "rerank", "product_fact", "readonly_sql"}
)


@dataclass(frozen=True)
class CacheKeyMaterial:
    """All inputs that may change the meaning of a reusable result."""

    operation: str
    model: str
    model_version: str
    embedding_dimensions: int | None
    data_version: str
    index_version: str
    normalized_query: str
    top_k: int | None
    reranker_instruct: str | None
    constraint_semantic_fingerprint: str | None
    region: str
    as_of: str

    def digest(self) -> str:
        payload = asdict(self)
        # Query and instruct text must never be recoverable from the cache key.
        payload["normalized_query"] = _sha256_text(self.normalized_query)
        payload["reranker_instruct"] = (
            _sha256_text(self.reranker_instruct) if self.reranker_instruct else None
        )
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return _sha256_text(encoded)


@dataclass(frozen=True)
class SafeCachePolicy:
    ttl_seconds: int = 86_400
    max_entries: int = 2_000

    def __post_init__(self) -> None:
        if self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if not 1 <= self.max_entries <= 100_000:
            raise ValueError("max_entries must be between 1 and 100000")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SafeCache:
    """SQLite-backed cache whose corruption never becomes application data."""

    def __init__(self, path: Path | str, *, policy: SafeCachePolicy | None = None) -> None:
        self.path = Path(path)
        self.policy = policy or SafeCachePolicy()
        self._lock = Lock()
        self._stats = {"hits": 0, "misses": 0, "writes": 0, "bypasses": 0, "corruptions": 0}

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=2.0)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                cache_key TEXT PRIMARY KEY,
                operation TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                last_accessed_at REAL NOT NULL
            )
            """
        )
        return connection

    @staticmethod
    def _allowed(
        material: CacheKeyMaterial,
        *,
        public_evaluation: bool,
        sensitive: bool,
        dynamic: bool,
    ) -> bool:
        return (
            material.operation in ALLOWED_OPERATIONS
            and public_evaluation
            and not sensitive
            and not dynamic
        )

    def get(
        self,
        material: CacheKeyMaterial,
        *,
        public_evaluation: bool = False,
        sensitive: bool = False,
        dynamic: bool = False,
    ) -> Any | None:
        if not self._allowed(
            material,
            public_evaluation=public_evaluation,
            sensitive=sensitive,
            dynamic=dynamic,
        ):
            self._stats["bypasses"] += 1
            return None
        now = time.time()
        try:
            with self._lock, self._connect() as connection:
                row = connection.execute(
                    "SELECT payload_json, payload_sha256, expires_at FROM cache_entries WHERE cache_key=?",
                    (material.digest(),),
                ).fetchone()
                if row is None:
                    self._stats["misses"] += 1
                    return None
                payload_json, expected_hash, expires_at = row
                if float(expires_at) <= now or _sha256_text(payload_json) != expected_hash:
                    connection.execute(
                        "DELETE FROM cache_entries WHERE cache_key=?", (material.digest(),)
                    )
                    if float(expires_at) > now:
                        self._stats["corruptions"] += 1
                    self._stats["misses"] += 1
                    return None
                try:
                    payload = json.loads(payload_json)
                except (TypeError, json.JSONDecodeError):
                    connection.execute(
                        "DELETE FROM cache_entries WHERE cache_key=?", (material.digest(),)
                    )
                    self._stats["corruptions"] += 1
                    self._stats["misses"] += 1
                    return None
                connection.execute(
                    "UPDATE cache_entries SET last_accessed_at=? WHERE cache_key=?",
                    (now, material.digest()),
                )
                self._stats["hits"] += 1
                return payload
        except sqlite3.Error:
            # A cache is an optimization. Database failures must cause a
            # recomputation, never a guessed or partially read value.
            self._stats["bypasses"] += 1
            return None

    def put(
        self,
        material: CacheKeyMaterial,
        payload: Any,
        *,
        public_evaluation: bool = False,
        sensitive: bool = False,
        dynamic: bool = False,
        complete: bool = True,
        success: bool = True,
    ) -> bool:
        if (
            not self._allowed(
                material,
                public_evaluation=public_evaluation,
                sensitive=sensitive,
                dynamic=dynamic,
            )
            or not complete
            or not success
        ):
            self._stats["bypasses"] += 1
            return False
        try:
            payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            self._stats["bypasses"] += 1
            return False
        now = time.time()
        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO cache_entries(
                        cache_key, operation, payload_json, payload_sha256,
                        created_at, expires_at, last_accessed_at
                    ) VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        payload_json=excluded.payload_json,
                        payload_sha256=excluded.payload_sha256,
                        created_at=excluded.created_at,
                        expires_at=excluded.expires_at,
                        last_accessed_at=excluded.last_accessed_at
                    """,
                    (
                        material.digest(),
                        material.operation,
                        payload_json,
                        _sha256_text(payload_json),
                        now,
                        now + self.policy.ttl_seconds,
                        now,
                    ),
                )
                excess = int(
                    connection.execute("SELECT COUNT(*) FROM cache_entries").fetchone()[0]
                ) - self.policy.max_entries
                if excess > 0:
                    connection.execute(
                        "DELETE FROM cache_entries WHERE cache_key IN "
                        "(SELECT cache_key FROM cache_entries ORDER BY last_accessed_at ASC LIMIT ?)",
                        (excess,),
                    )
                self._stats["writes"] += 1
                return True
        except sqlite3.Error:
            self._stats["bypasses"] += 1
            return False

    def clear(self) -> int:
        if not self.path.exists():
            return 0
        try:
            with self._lock, self._connect() as connection:
                count = int(connection.execute("SELECT COUNT(*) FROM cache_entries").fetchone()[0])
                connection.execute("DELETE FROM cache_entries")
                return count
        except sqlite3.Error:
            self._stats["bypasses"] += 1
            return 0

    def stats(self) -> dict[str, int | float]:
        snapshot = dict(self._stats)
        total = snapshot["hits"] + snapshot["misses"]
        snapshot["hit_rate"] = round(snapshot["hits"] / total, 6) if total else 0.0
        return snapshot
