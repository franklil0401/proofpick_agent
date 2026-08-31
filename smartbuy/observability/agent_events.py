"""Content-free, bounded Agent monitoring snapshots."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from threading import Lock
from typing import Any


class AgentMonitor:
    def __init__(self, max_runs: int = 50) -> None:
        self._runs: deque[dict[str, Any]] = deque(maxlen=max_runs)
        self._orchestration_events: deque[dict[str, Any]] = deque(maxlen=max_runs * 2)
        self._lock = Lock()

    def record(self, payload: dict[str, Any]) -> None:
        def bounded_value(value: Any) -> Any:
            if value is None or isinstance(value, (bool, int, float)):
                return value
            if isinstance(value, list):
                return [bounded_value(item) for item in value[:8]]
            return str(value)[:120]

        allowed = {
            "session_id": str(payload.get("session_id", ""))[:64],
            "latency_ms": float(payload.get("latency_ms", 0.0)),
            "tool_call_count": int(payload.get("tool_call_count", 0)),
            "tools": list(payload.get("tools", []))[:12],
            "statuses": list(payload.get("statuses", []))[:12],
            "stop_reason": str(payload.get("stop_reason", ""))[:200],
            "abstained": bool(payload.get("abstained", False)),
            "estimated_cost_cny": float(payload.get("estimated_cost_cny", 0.0)),
            "constraint_checker_version": str(payload.get("constraint_checker_version", ""))[:80],
            "constraint_statuses": list(payload.get("constraint_statuses", []))[:20],
            "constraint_degraded": bool(payload.get("constraint_degraded", False)),
            "constraint_check_latency_ms": float(payload.get("constraint_check_latency_ms", 0.0)),
            "constraint_candidates": [
                {
                    "model_id": str(item.get("model_id", ""))[:80],
                    "status": str(item.get("status", ""))[:20],
                    "eligible": bool(item.get("eligible", False)),
                    "violated_fields": list(item.get("violated_fields", []))[:12],
                    "unknown_fields": list(item.get("unknown_fields", []))[:12],
                    "conflict_fields": list(item.get("conflict_fields", []))[:12],
                    "constraint_results": [
                        {
                            "field": str(result.get("field", ""))[:80],
                            "status": str(result.get("status", ""))[:20],
                            "actual_value": bounded_value(result.get("actual_value")),
                            "required_value": bounded_value(result.get("required_value")),
                            "evidence_id": str(result.get("evidence_id") or "")[:120] or None,
                            "source_id": str(result.get("source_id") or "")[:120] or None,
                        }
                        for result in list(item.get("constraint_results", []))[:16]
                        if isinstance(result, dict)
                    ],
                }
                for item in list(payload.get("constraint_candidates", []))[:20]
                if isinstance(item, dict)
            ],
        }
        with self._lock:
            self._runs.append(allowed)

    def record_orchestration_event(self, payload: dict[str, Any]) -> None:
        """Store only bounded orchestration metadata, never prompts, IDs or checkpoint keys."""
        allowed = {
            "type": str(payload.get("type", ""))[:64],
            "requested": str(payload.get("requested", ""))[:24],
            "selected": str(payload.get("selected") or "")[:24] or None,
            "status": str(payload.get("status", ""))[:40],
            "reason": str(payload.get("reason") or "")[:80] or None,
        }
        with self._lock:
            self._orchestration_events.append(allowed)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            runs = deepcopy(list(self._runs))
            orchestration_events = deepcopy(list(self._orchestration_events))
        latencies = sorted(item["latency_ms"] for item in runs)
        p95_index = max(0, min(len(latencies) - 1, int(len(latencies) * 0.95))) if latencies else 0
        return {
            "run_count": len(runs),
            "abstain_count": sum(item["abstained"] for item in runs),
            "degraded_run_count": sum("degraded" in item["statuses"] or "unavailable" in item["statuses"] for item in runs),
            "average_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
            "p95_latency_ms": round(latencies[p95_index], 3) if latencies else 0.0,
            "estimated_cost_cny": round(sum(item["estimated_cost_cny"] for item in runs), 8),
            "constraint_checked_run_count": sum(bool(item["constraint_checker_version"]) for item in runs),
            "constraint_degraded_run_count": sum(item["constraint_degraded"] for item in runs),
            "average_constraint_check_latency_ms": round(
                sum(item["constraint_check_latency_ms"] for item in runs) / len(runs), 3
            ) if runs else 0.0,
            "recent_runs": runs[-10:],
            "recent_orchestration_events": orchestration_events[-20:],
        }


agent_monitor = AgentMonitor()
