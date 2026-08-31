"""Safe LangGraph checkpoint backends for tests and local Windows MVP use."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, ConfigDict, Field


CHECKPOINT_STATE_VERSION = "proofpick-checkpoint-v1"


def strict_serializer() -> JsonPlusSerializer:
    """Use MsgPack/JSON only and allow exactly one inert built-in constructor."""
    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_json_modules=[("builtins", "dict")],
    )


class ThreadIdentity(BaseModel):
    """Stable user/session/thread isolation without storing those values in SQLite keys."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)

    @property
    def storage_key(self) -> str:
        raw = f"{CHECKPOINT_STATE_VERSION}\x1f{self.user_id}\x1f{self.session_id}\x1f{self.thread_id}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CheckpointBackend(Protocol):
    async def start(self) -> BaseCheckpointSaver: ...

    async def clear(self, identity: ThreadIdentity) -> None: ...

    async def close(self) -> None: ...


class InMemoryCheckpointBackend:
    """Test-only checkpointer; state does not survive a process restart."""

    def __init__(self) -> None:
        self.saver = InMemorySaver(serde=strict_serializer())

    async def start(self) -> BaseCheckpointSaver:
        return self.saver

    async def clear(self, identity: ThreadIdentity) -> None:
        await self.saver.adelete_thread(identity.storage_key)

    async def close(self) -> None:
        return None

class SqliteCheckpointBackend:
    """Repository-external local MVP persistence; not a production HA backend."""

    def __init__(self, path: Path, *, repository_root: Path) -> None:
        self.path = path.expanduser().resolve()
        self.repository_root = repository_root.resolve()
        if self.path.is_relative_to(self.repository_root):
            raise ValueError("checkpoint database must be outside the Git repository")
        self._connection: aiosqlite.Connection | None = None
        self._saver: AsyncSqliteSaver | None = None

    async def start(self) -> BaseCheckpointSaver:
        if self._saver is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = await aiosqlite.connect(self.path)
            self._saver = AsyncSqliteSaver(self._connection, serde=strict_serializer())
            await self._saver.setup()
        return self._saver

    async def clear(self, identity: ThreadIdentity) -> None:
        saver = await self.start()
        await saver.adelete_thread(identity.storage_key)

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
        self._connection = None
        self._saver = None


class PostgresCheckpointBackend:
    """Migration boundary only; deployment is intentionally outside V2-1C."""

    async def start(self) -> BaseCheckpointSaver:
        raise NotImplementedError("PostgreSQL checkpointer is not deployed in V2-1C")

    async def clear(self, identity: ThreadIdentity) -> None:
        raise NotImplementedError("PostgreSQL checkpointer is not deployed in V2-1C")

    async def close(self) -> None:
        return None
