"""Subprocess helper proving repository-external SQLite checkpoint recovery."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from smartbuy.constraints import CandidateVerification, VerificationBatch, VerificationStatus
from smartbuy.domain import CandidateDecision, ConstraintStatus, DecisionReport
from smartbuy.memory import LongTermPreferenceStore
from smartbuy.orchestration import OrchestratorRequest
from smartbuy.orchestration.checkpoints import SqliteCheckpointBackend
from smartbuy.orchestration.langgraph_adapter import LangGraphOrchestrator


class WorkerAgent:
    def __init__(self, runtime: Path) -> None:
        self.preference_memory = LongTermPreferenceStore(runtime / "preferences.json")

    async def run(self, query, **_kwargs):
        model_id = "dell-u2723qe-cn"
        checked_at = "2026-08-31T00:00:00Z"
        verification = VerificationBatch(
            verifier_version="smartbuy-constraint-checker-v1",
            checked_at=checked_at,
            constraint_set_version="smartbuy-constraint-set-v1",
            candidate_pool_model_ids=[model_id],
            candidates=[
                CandidateVerification(
                    model_id=model_id,
                    overall_status=VerificationStatus.PASSED,
                    eligible=True,
                    checked_at=checked_at,
                    verifier_version="smartbuy-constraint-checker-v1",
                )
            ],
            eligible_model_ids=[model_id],
            semantic_fingerprint="checkpoint-worker",
        )
        return DecisionReport(
            request_summary=query,
            constraint_verification=verification,
            candidates=[
                CandidateDecision(
                    model_id=model_id,
                    overall_status=ConstraintStatus.MATCHED,
                    eligible=True,
                    verifier_status=VerificationStatus.PASSED,
                )
            ],
            recommended_model_ids=[model_id],
            stop_reason="checkpoint worker completed",
        )


async def run(args) -> None:
    runtime = Path(args.runtime).resolve()
    backend = SqliteCheckpointBackend(
        runtime / "checkpoints.sqlite3",
        repository_root=Path(__file__).resolve().parents[3],
    )
    graph = LangGraphOrchestrator(WorkerAgent(runtime), backend)
    common = {
        "query": "跨进程恢复",
        "user_id": "worker-user",
        "session_id": "worker-session",
        "thread_id": "worker-thread",
    }
    if args.phase == "start":
        result = await graph.run(
            OrchestratorRequest(**common, clarification_question="是否继续？")
        )
    else:
        result = await graph.run(OrchestratorRequest(**common, resume_value="继续"))
    print(result.model_dump_json())
    await graph.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["start", "resume"])
    parser.add_argument("runtime")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
