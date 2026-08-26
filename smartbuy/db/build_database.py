"""Build an external SQLite database deterministically from governed source data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from smartbuy.data.derive import evidence_rows, source_rows
from smartbuy.data.loader import CATALOG_PATH, load_catalog
from smartbuy.data.quality import validate_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = Path("C:/ai/smartbuy-stage3/smartbuy_monitors_v1.sqlite")
SCHEMA_PATH = Path(__file__).with_name("schema_v1.sql")
TABLES = ("products", "price_observations", "source_records", "evidence_records")


def _inside_project(path: Path) -> bool:
    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
        return True
    except ValueError:
        return False


def _insert_rows(connection: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    values = []
    for row in rows:
        values.append(
            tuple(
                json.dumps(row[column], ensure_ascii=False, sort_keys=True)
                if table == "evidence_records" and column == "normalized_value"
                else row[column]
                for column in columns
            )
        )
    placeholders = ",".join("?" for _ in columns)
    connection.executemany(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})", values
    )


def database_summary(path: Path | str) -> dict[str, Any]:
    connection = sqlite3.connect(str(path))
    try:
        counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}
        fk_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        logical_rows: dict[str, list[list[Any]]] = {}
        for table in TABLES:
            logical_rows[table] = [list(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1")]
        digest = hashlib.sha256(
            json.dumps(logical_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {"counts": counts, "foreign_key_violations": len(fk_violations), "integrity": integrity, "logical_sha256": digest}
    finally:
        connection.close()


def build_database(output: Path | str = DEFAULT_OUTPUT, catalog_path: Path | str = CATALOG_PATH, *, allow_project_output: bool = False) -> dict[str, Any]:
    output_path = Path(output).resolve()
    if _inside_project(output_path) and not allow_project_output:
        raise ValueError("runtime database must stay outside the Git workspace")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    catalog = load_catalog(catalog_path)
    report = validate_catalog(catalog)
    if not report.passed:
        raise RuntimeError("catalog quality gate failed")

    sources = source_rows(catalog)
    evidence = evidence_rows(catalog)
    with tempfile.NamedTemporaryFile(prefix="smartbuy-stage3-", suffix=".sqlite", dir=output_path.parent, delete=False) as handle:
        temporary_path = Path(handle.name)
    try:
        connection = sqlite3.connect(str(temporary_path))
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            with connection:
                _insert_rows(connection, "products", list(catalog.products))
                _insert_rows(connection, "source_records", sources)
                _insert_rows(connection, "price_observations", list(catalog.price_observations))
                _insert_rows(connection, "evidence_records", evidence)
                connection.executemany(
                    "INSERT INTO metadata(key, value) VALUES (?, ?)",
                    (("schema_version", catalog.schema_version), ("data_version", catalog.data_version)),
                )
        finally:
            connection.close()
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return database_summary(output_path)


def export_csv(database: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database))
    try:
        for table in TABLES:
            cursor = connection.execute(f"SELECT * FROM {table} ORDER BY 1")
            with (output_dir / f"{table}.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([item[0] for item in cursor.description])
                writer.writerows(cursor.fetchall())
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--export-dir", type=Path)
    args = parser.parse_args()
    summary = build_database(args.output, args.catalog)
    if args.export_dir:
        export_csv(args.output, args.export_dir)
    print(json.dumps({"status": "completed", **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
