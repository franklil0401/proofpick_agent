"""Evidence completeness and four-state decision tests."""

from __future__ import annotations

import sqlite3

import pytest

from smartbuy.db.build_database import build_database
from smartbuy.tools import EvidenceCheckTool


@pytest.fixture()
def database(tmp_path):
    path = tmp_path / "catalog.sqlite"
    build_database(path)
    return path


async def assess(tool, model_id, field, operator="eq", value=True):
    result = await tool.invoke(
        {
            "model_ids": [model_id],
            "required_fields": [field],
            "constraints": [{"field": field, "operator": operator, "value": value}],
            "reason": "test",
        }
    )
    return result.data["models"][model_id][0]


@pytest.mark.asyncio
async def test_four_states_are_not_derived_from_reranker_score(database):
    tool = EvidenceCheckTool(database)
    assert (await assess(tool, "dell-u2723qe-cn", "usb_c_video"))["status"] == "matched"
    assert (await assess(tool, "dell-u2724d-cn", "usb_c_video"))["status"] == "not_matched"
    assert (await assess(tool, "dell-u2723qe-cn", "camera"))["status"] == "unknown"
    conflict = await assess(tool, "benq-pd2705u-us", "usb_c_power_delivery_w", "gte", 60)
    assert conflict["status"] == "conflict"
    assert len(conflict["evidence"]) == 2


@pytest.mark.asyncio
async def test_wrong_region_and_missing_evidence_are_unknown(database):
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE source_records SET region='US' WHERE source_id='src-dell-u2723qe-cn-product'"
    )
    connection.commit()
    connection.close()
    result = await assess(EvidenceCheckTool(database), "dell-u2723qe-cn", "resolution", "eq", "3840x2160")
    assert result["status"] == "unknown"


@pytest.mark.asyncio
async def test_missing_model_is_unknown(database):
    result = await assess(EvidenceCheckTool(database), "unknown-model", "resolution", "eq", "3840x2160")
    assert result["status"] == "unknown"


@pytest.mark.asyncio
async def test_stale_price_is_unknown(database):
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE price_observations SET observed_at='2020-01-01T00:00:00+08:00' "
        "WHERE model_id='dell-u2723qe-cn'"
    )
    connection.commit()
    connection.close()
    result = await assess(EvidenceCheckTool(database), "dell-u2723qe-cn", "price_cny", "lte", 4000)
    assert result["status"] == "unknown"
    assert "超过" in result["reason"]


@pytest.mark.asyncio
async def test_empty_candidates_fail_closed(database):
    result = await EvidenceCheckTool(database).invoke(
        {"model_ids": [], "required_fields": ["resolution"], "constraints": [], "reason": "test"}
    )
    assert result.status == "failed"
    assert result.error_code == "INVALID_EVIDENCE_REQUEST"


@pytest.mark.asyncio
async def test_resolution_minimum_uses_normalized_pixel_count(database):
    result = await assess(
        EvidenceCheckTool(database),
        "asus-pa279crv-cn",
        "resolution",
        "gte",
        "3840x2160",
    )
    assert result["status"] == "matched"
