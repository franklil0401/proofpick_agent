"""Merge independently generated Stage 6 checkpoints by frozen prediction key."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from smartbuy.eval.run_stage6_eval import GROUPS


def _digest(row: dict) -> str:
    return hashlib.sha256(
        json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def merge(
    inputs: list[Path],
    output: Path,
    *,
    first_wins_audit: Path | None = None,
    expected_count: int | None = None,
) -> dict[str, int | str]:
    rows: dict[tuple[str, str, int], dict] = {}
    config_hash: str | None = None
    duplicate_count = 0
    conflicting_duplicates: list[dict[str, str | int]] = []
    for path in inputs:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if config_hash is None:
                config_hash = str(row["config_hash"])
            elif row["config_hash"] != config_hash:
                raise RuntimeError("cannot merge checkpoints with different config hashes")
            prediction = row["prediction"]
            key = (
                str(prediction["case_id"]),
                str(prediction["experiment_group"]),
                int(prediction["repetition"]),
            )
            if key in rows:
                duplicate_count += 1
                if rows[key] != row:
                    if first_wins_audit is None:
                        raise RuntimeError(f"conflicting duplicate checkpoint key: {key}")
                    conflicting_duplicates.append(
                        {
                            "case_id": key[0],
                            "experiment_group": key[1],
                            "repetition": key[2],
                            "kept_sha256": _digest(rows[key]),
                            "discarded_sha256": _digest(row),
                        }
                    )
                continue
            rows[key] = row
    if expected_count is not None and len(rows) != expected_count:
        raise RuntimeError(
            f"merged checkpoint has {len(rows)} unique predictions, expected {expected_count}"
        )
    ordered = sorted(
        rows.values(),
        key=lambda row: (
            int(row["prediction"]["repetition"]),
            str(row["prediction"]["case_id"]),
            GROUPS.index(str(row["prediction"]["experiment_group"])),
        ),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in ordered),
        encoding="utf-8",
        newline="\n",
    )
    audit = {
        "selection_policy": "first occurrence wins",
        "prediction_count": len(ordered),
        "duplicate_count": duplicate_count,
        "conflicting_duplicate_count": len(conflicting_duplicates),
        "config_hash": config_hash or "",
        "conflicts": conflicting_duplicates,
    }
    if first_wins_audit is not None:
        first_wins_audit.parent.mkdir(parents=True, exist_ok=True)
        first_wins_audit.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return {key: value for key, value in audit.items() if key != "conflicts"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--first-wins-audit", type=Path)
    parser.add_argument("--expected-count", type=int)
    args = parser.parse_args()
    print(
        json.dumps(
            merge(
                args.input,
                args.output,
                first_wins_audit=args.first_wins_audit,
                expected_count=args.expected_count,
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
