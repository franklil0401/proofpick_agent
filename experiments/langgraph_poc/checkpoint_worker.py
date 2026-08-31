"""Subprocess helper for the PoC cross-process checkpoint test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .checkpoint import FileBackedMemorySaver
from .fake_tools import FakeToolRegistry
from .fixtures import fixture
from .graph import LangGraphPoc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("start", "resume"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    tools = FakeToolRegistry()
    graph = LangGraphPoc(
        args.database,
        checkpointer=FileBackedMemorySaver(args.checkpoint),
        tools=tools,
    )
    if args.mode == "start":
        state = graph.invoke(
            fixture(case_id="m12", pause_after_tools=True), thread_id="m12-subprocess"
        )
    else:
        state = graph.resume(thread_id="m12-subprocess", value={"continue": True})
    payload = {
        "interrupted": "__interrupt__" in state,
        "tool_call_count": state.get("tool_call_count", 0),
        "checker_executed": state.get("checker_executed", False),
        "recommended_model_ids": state.get("final_report", {}).get(
            "recommended_model_ids", []
        ),
        "process_tool_attempts": {
            name: tools.attempts_for(name)
            for name in ("text2sql", "kb_search", "kb_search_targeted")
        },
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
