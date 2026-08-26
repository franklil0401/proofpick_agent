from __future__ import annotations

from smartbuy.db.build_database import build_database


def test_database_build_is_idempotent_and_integral(tmp_path) -> None:
    output = tmp_path / "fixture.sqlite"

    first = build_database(output, allow_project_output=True)
    second = build_database(output, allow_project_output=True)

    assert first == second
    assert first["integrity"] == "ok"
    assert first["foreign_key_violations"] == 0
    assert first["counts"] == {
        "products": 12,
        "price_observations": 4,
        "source_records": 16,
        "evidence_records": 180,
    }
