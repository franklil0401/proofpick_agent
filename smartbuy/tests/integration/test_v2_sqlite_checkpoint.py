"""Cross-process AsyncSqliteSaver recovery for the Windows local MVP."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _worker(phase: str, runtime: Path) -> dict:
    root = Path(__file__).resolve().parents[3]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root)
    environment["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [
            sys.executable,
            str(root / "smartbuy/tests/fixtures/v2_checkpoint_worker.py"),
            phase,
            str(runtime),
        ],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    return json.loads(result.stdout.strip())


def test_async_sqlite_checkpoint_survives_process_restart(tmp_path):
    first = _worker("start", tmp_path)
    assert first["status"] == "interrupted"
    assert first["report"] is None
    resumed = _worker("resume", tmp_path)
    assert resumed["status"] == "completed"
    assert resumed["resumed"] is True
    assert resumed["report"]["recommended_model_ids"] == ["dell-u2723qe-cn"]
