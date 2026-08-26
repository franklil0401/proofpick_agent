"""In-memory, content-free API usage accounting for bounded development tests."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock


@dataclass(frozen=True)
class UsageRecord:
    operation: str
    model: str
    success: bool
    attempts: int
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    item_count: int = 0
    estimated_cost_cny: float = 0.0
    degraded: bool = False
    status_code: int | None = None


class UsageLedger:
    """Keep sanitized records in memory; request and response content are excluded."""

    _INPUT_RATES = {
        "qwen-plus": 0.8,
        "text-embedding-v4": 0.5,
        "qwen3-rerank": 0.5,
    }
    _OUTPUT_RATES = {"qwen-plus": 2.0}

    def __init__(self) -> None:
        self._records: list[UsageRecord] = []
        self._lock = Lock()

    @classmethod
    def estimate_cost(
        cls, model: str, input_tokens: int = 0, output_tokens: int = 0
    ) -> float:
        input_cost = input_tokens * cls._INPUT_RATES.get(model, 0.0) / 1_000_000
        output_cost = output_tokens * cls._OUTPUT_RATES.get(model, 0.0) / 1_000_000
        return input_cost + output_cost

    def add(self, record: UsageRecord) -> None:
        with self._lock:
            self._records.append(record)

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            return [asdict(record) for record in self._records]

    def summary(self) -> dict[str, object]:
        with self._lock:
            records = list(self._records)
        return {
            "call_count": len(records),
            "successful_calls": sum(record.success for record in records),
            "degraded_calls": sum(record.degraded for record in records),
            "input_tokens": sum(record.input_tokens for record in records),
            "output_tokens": sum(record.output_tokens for record in records),
            "estimated_cost_cny": round(sum(record.estimated_cost_cny for record in records), 8),
        }
