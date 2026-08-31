"""Opt-in orchestration compatibility layer for ProofPick V2."""

from .contracts import (
    ORCHESTRATION_CONTRACT_VERSION,
    OrchestratorKind,
    OrchestratorRequest,
    OrchestratorResult,
    OrchestrationStatus,
)
from .react_adapter import ReactOrchestrator
from .selector import OrchestratorSelector, OrchestratorSettings

__all__ = [
    "ORCHESTRATION_CONTRACT_VERSION",
    "OrchestratorKind",
    "OrchestratorRequest",
    "OrchestratorResult",
    "OrchestrationStatus",
    "ReactOrchestrator",
    "OrchestratorSelector",
    "OrchestratorSettings",
]
