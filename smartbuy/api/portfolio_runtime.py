"""Explicit, default-off runtime for the V2 multi-domain portfolio UI.

The V1 `/api/smartbuy/chat` route remains unchanged.  This module only builds
the already-implemented generic Domain Agent when the caller explicitly opts
in and repository-external data/index pointers validate successfully.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from smartbuy.agent import DomainDecisionAgent
from smartbuy.config import load_bailian_settings
from smartbuy.constraint_proposals.engine import NaturalConstraintEngine
from smartbuy.domain_packs import DomainPackRegistry
from smartbuy.memory import DomainPreferenceMemoryStore
from smartbuy.observability import UsageLedger
from smartbuy.orchestration import ReactOrchestrator
from smartbuy.product_packs import DomainProductPackManager
from smartbuy.providers import BailianProvider
from smartbuy.retrieval.domain_index import DomainIndexManager
from smartbuy.tools.domain import (
    DomainConstraintCheckerTool,
    DomainEvidenceCheckTool,
    DomainKBSearchTool,
    DomainProductQueryTool,
    DomainReadonlyRepository,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_DOMAINS = frozenset({"laptop", "headphone"})


@dataclass(frozen=True)
class PortfolioRuntime:
    domain_id: str
    data_version: str
    index_version: str
    orchestrator: ReactOrchestrator
    provider: BailianProvider


class PortfolioRuntimeManager:
    """Lazily select a validated runtime; never creates data or indices."""

    def __init__(self) -> None:
        self._runtimes: dict[str, PortfolioRuntime] = {}

    @staticmethod
    def enabled() -> bool:
        return os.getenv("PROOFPICK_DOMAIN_AGENT_ENABLED", "false").strip().casefold() == "true"

    @staticmethod
    def runtime_root() -> Path:
        root = Path(
            os.getenv("PROOFPICK_V2_RUNTIME_ROOT", "C:/ai/proofpick-v2-rc")
        ).resolve()
        try:
            root.relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            return root
        raise ValueError("V2 runtime must stay outside the repository")

    def get(self, domain_id: str) -> PortfolioRuntime:
        if not self.enabled():
            raise RuntimeError("domain_agent_disabled")
        if domain_id not in SUPPORTED_DOMAINS:
            raise ValueError("portfolio domain runtime is unsupported")
        if domain_id in self._runtimes:
            return self._runtimes[domain_id]
        root = self.runtime_root()
        pack = DomainPackRegistry(PROJECT_ROOT / "smartbuy" / "domain_packs").load(domain_id)
        domain_root = root / domain_id
        data_manager = DomainProductPackManager(
            domain_root / "data",
            domain_pack_path=PROJECT_ROOT / "smartbuy" / "domain_packs" / domain_id,
        )
        snapshot = data_manager.current()
        index_manager = DomainIndexManager(
            domain_root / "index",
            data_manager=data_manager,
            domain_id=domain_id,
            domain_pack_version=pack.version,
        )
        index = index_manager.current()
        if index.data_version != snapshot.data_version:
            raise RuntimeError("data_index_version_mismatch")
        repository = DomainReadonlyRepository(snapshot, pack)
        provider = BailianProvider(load_bailian_settings(), ledger=UsageLedger())
        memory = DomainPreferenceMemoryStore(root / "memory", pack)
        agent = DomainDecisionAgent(
            pack,
            repository,
            DomainProductQueryTool(repository),
            DomainEvidenceCheckTool(repository),
            DomainConstraintCheckerTool(repository),
            NaturalConstraintEngine(pack),
            memory,
            kb_search=DomainKBSearchTool(index_manager, provider),
        )
        runtime = PortfolioRuntime(
            domain_id=domain_id,
            data_version=snapshot.data_version,
            index_version=index.index_version,
            orchestrator=ReactOrchestrator(agent),
            provider=provider,
        )
        self._runtimes[domain_id] = runtime
        return runtime

    async def close(self) -> None:
        for runtime in self._runtimes.values():
            await runtime.provider.aclose()
        self._runtimes.clear()
