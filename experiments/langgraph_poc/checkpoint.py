"""Test-only file-backed LangGraph checkpointer.

The saver persists LangGraph's in-memory checkpoint structures to a trusted
temporary file. It exists only to prove cross-instance recovery in the PoC;
production adoption must use a supported durable saver.
"""

from __future__ import annotations

import os
import pickle
import threading
from pathlib import Path
from typing import Any, Sequence

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import ChannelVersions, Checkpoint, CheckpointMetadata
from langgraph.checkpoint.memory import InMemorySaver


class CheckpointCorruptedError(RuntimeError):
    """Raised when a trusted PoC checkpoint cannot be decoded."""


class FileBackedMemorySaver(InMemorySaver):
    """Persist `InMemorySaver` state for a cross-instance PoC test."""

    def __init__(self, path: Path | str) -> None:
        super().__init__()
        self.path = Path(path)
        self._file_lock = threading.RLock()
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        try:
            with self.path.open("rb") as handle:
                payload = pickle.load(handle)  # noqa: S301 - trusted tmp PoC file only
            if set(payload) != {"storage", "writes", "blobs"}:
                raise ValueError("unexpected checkpoint payload")
            for thread_id, namespaces in payload["storage"].items():
                for namespace, checkpoints in namespaces.items():
                    self.storage[thread_id][namespace].update(checkpoints)
            self.writes.update(payload["writes"])
            self.blobs.update(payload["blobs"])
        except (EOFError, OSError, pickle.PickleError, TypeError, ValueError) as exc:
            raise CheckpointCorruptedError("PoC checkpoint is corrupt; recovery refused") from exc

    def _flush(self) -> None:
        with self._file_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            storage = {
                thread_id: {
                    namespace: dict(checkpoints)
                    for namespace, checkpoints in namespaces.items()
                }
                for thread_id, namespaces in self.storage.items()
            }
            with temporary.open("wb") as handle:
                pickle.dump(
                    {
                        "storage": storage,
                        "writes": dict(self.writes),
                        "blobs": dict(self.blobs),
                    },
                    handle,
                    protocol=pickle.HIGHEST_PROTOCOL,
                )
            os.replace(temporary, self.path)

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        with self._file_lock:
            updated = super().put(config, checkpoint, metadata, new_versions)
            self._flush()
        return updated

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        with self._file_lock:
            super().put_writes(config, writes, task_id, task_path)
            self._flush()

    def delete_thread(self, thread_id: str) -> None:
        with self._file_lock:
            super().delete_thread(thread_id)
            self._flush()
