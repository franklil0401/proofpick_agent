"""Safe Alibaba Cloud Model Studio configuration loaded from process environment."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is absent or invalid."""


_WORKSPACE_PATTERN = re.compile(r"^ws-[A-Za-z0-9]+$")


@dataclass(frozen=True)
class BailianSettings:
    """Resolved Model Studio settings without a serializable secret representation."""

    api_key: str = field(repr=False)
    workspace_id: str
    chat_model: str = "qwen-plus"
    embedding_model: str = "text-embedding-v4"
    embedding_dimensions: int = 1024
    reranker_model: str = "qwen3-rerank"
    region: str = "cn-beijing"

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ConfigurationError("Qianwen_api_key is missing from the process environment")
        if not _WORKSPACE_PATTERN.fullmatch(self.workspace_id):
            raise ConfigurationError("Qianwen_workspace_id has an invalid format")
        if self.embedding_dimensions != 1024:
            raise ConfigurationError("text-embedding-v4 dimensions must remain fixed at 1024")

    @property
    def compatible_base_url(self) -> str:
        return (
            f"https://{self.workspace_id}.{self.region}.maas.aliyuncs.com/"
            "compatible-mode/v1"
        )

    @property
    def chat_url(self) -> str:
        return f"{self.compatible_base_url}/chat/completions"

    @property
    def embedding_url(self) -> str:
        return f"{self.compatible_base_url}/embeddings"

    @property
    def rerank_url(self) -> str:
        return (
            f"https://{self.workspace_id}.{self.region}.maas.aliyuncs.com/"
            "compatible-api/v1/reranks"
        )

    def availability(self) -> dict[str, str]:
        """Return safe configuration status; never expose credential values."""
        return {
            "Qianwen_api_key": "configured",
            "Qianwen_workspace_id": "configured",
        }

    def youtu_environment(self) -> dict[str, str]:
        """Build in-memory Youtu-RAG mappings for the current child process only."""
        return {
            "UTU_LLM_TYPE": "chat.completions",
            "UTU_LLM_MODEL": self.chat_model,
            "UTU_LLM_BASE_URL": self.compatible_base_url,
            "UTU_LLM_API_KEY": self.api_key,
            "UTU_EMBEDDING_MODEL": self.embedding_model,
            "UTU_EMBEDDING_URL": self.compatible_base_url,
            "UTU_EMBEDDING_API_KEY": self.api_key,
            "UTU_EMBEDDING_DIMENSIONS": str(self.embedding_dimensions),
            "UTU_RERANKER_MODEL": self.reranker_model,
            "UTU_RERANKER_URL": self.rerank_url,
            "UTU_RERANKER_BASE_URL": self.rerank_url,
            "UTU_RERANKER_API_KEY": self.api_key,
        }


def load_bailian_settings() -> BailianSettings:
    """Load inherited process variables using the names agreed by the project."""
    api_key = os.getenv("Qianwen_api_key", "").strip()
    workspace_id = os.getenv("Qianwen_workspace_id", "").strip()
    if not api_key:
        raise ConfigurationError("Qianwen_api_key is missing from the process environment")
    if not workspace_id:
        raise ConfigurationError("Qianwen_workspace_id is missing from the process environment")
    return BailianSettings(api_key=api_key, workspace_id=workspace_id)
