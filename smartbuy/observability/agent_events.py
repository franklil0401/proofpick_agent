"""Content-free, bounded Agent monitoring snapshots."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from threading import Lock
from typing import Any


class AgentMonitor:
    def __init__(self, max_runs: int = 50) -> None:
        self._runs: deque[dict[str, Any]] = deque(maxlen=max_runs)
        self._lock = Lock()

    def record(self, payload: dict[str, Any]) -> None:
        allowed = {
            "session_id": str(payload.get("session_id", ""))[:64],
            "latency_ms": float(payload.get("latency_ms", 0.0)),
            "tool_call_count": int(payload.get("tool_call_count", 0)),
            "tools": list(payload.get("tools", []))[:12],
            "statuses": list(payload.get("statuses", []))[:12],
            "stop_reason": str(payload.get("stop_reason", ""))[:200],
            "abstained": bool(payload.get("abstained", False)),
            "estimated_cost_cny": float(payload.get("estimated_cost_cny", 0.0)),
        }
        with self._lock:
            self._runs.append(allowed)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            runs = deepcopy(list(self._runs))
        latencies = sorted(item["latency_ms"] for item in runs)
        p95_index = max(0, min(len(latencies) - 1, int(len(latencies) * 0.95))) if latencies else 0
        return {
            "run_count": len(runs),
            "abstain_count": sum(item["abstained"] for item in runs),
            "degraded_run_count": sum("degraded" in item["statuses"] or "unavailable" in item["statuses"] for item in runs),
            "average_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
            "p95_latency_ms": round(latencies[p95_index], 3) if latencies else 0.0,
            "estimated_cost_cny": round(sum(item["estimated_cost_cny"] for item in runs), 8),
            "recent_runs": runs[-10:],
        }


agent_monitor = AgentMonitor()
