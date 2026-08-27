"""Text2SQL safety and gold-result tests."""

from __future__ import annotations

import pytest

from smartbuy.db.build_database import build_database
from smartbuy.tools.text2sql import SQLValidationError, Text2SQLTool, validate_select_sql


@pytest.fixture()
def database(tmp_path):
    path = tmp_path / "catalog.sqlite"
    build_database(path)
    return path


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM products",
        "SELECT model_id FROM products; DROP TABLE products",
        "PRAGMA table_info(products)",
        "SELECT name FROM sqlite_master",
        "SELECT model_id FROM products -- bypass",
        "ATTACH DATABASE 'x' AS other",
    ],
)
def test_validator_rejects_unsafe_sql(sql):
    with pytest.raises(SQLValidationError):
        validate_select_sql(sql)


def test_readonly_authorizer_rejects_non_allowlisted_column(database):
    tool = Text2SQLTool(database)
    with pytest.raises(SQLValidationError):
        tool._execute("SELECT rowid FROM products")


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (
            "SELECT p.model_id FROM products p JOIN price_observations po ON po.model_id=p.model_id "
            "WHERE po.price_cny <= 2500 ORDER BY p.model_id",
            ["dell-g2724d-cn", "dell-s2722qc-cn"],
        ),
        (
            "SELECT model_id FROM products WHERE display_size_inch=27 AND resolution='3840x2160' ORDER BY model_id",
            [
                "asus-pa279crv-cn", "benq-ex2710u-cn", "benq-pd2705u-us", "benq-pd2725u-ca",
                "dell-s2722qc-cn", "dell-u2723qe-cn", "lg-27up850k-w-cn",
            ],
        ),
        (
            "SELECT model_id FROM products WHERE is_oled=0 AND usb_c_video=1 "
            "AND usb_c_power_delivery_w>=90 ORDER BY model_id",
            ["asus-pa279crv-cn", "asus-pa27jcv-cn", "dell-u2723qe-cn", "lg-27up850k-w-cn"],
        ),
        (
            "SELECT model_id FROM products WHERE refresh_rate_hz>=120 AND is_oled=0 ORDER BY model_id",
            ["benq-ex2710u-cn", "dell-g2724d-cn", "dell-u2724d-cn"],
        ),
        (
            "SELECT model_id FROM products WHERE region='CN' AND display_size_inch=27 "
            "AND resolution='3840x2160' AND usb_c_video=1 AND usb_c_power_delivery_w>=90 ORDER BY model_id",
            ["asus-pa279crv-cn", "dell-u2723qe-cn", "lg-27up850k-w-cn"],
        ),
        (
            "SELECT model_id FROM products WHERE width_mm IS NULL ORDER BY model_id",
            ["dell-u2724d-cn"],
        ),
        ("SELECT model_id FROM products WHERE display_size_inch=49", []),
    ],
)
def test_generated_select_matches_manual_gold(database, sql, expected):
    rows, _ = Text2SQLTool(database)._execute(sql)
    assert [row["model_id"] for row in rows] == expected


@pytest.mark.asyncio
async def test_invalid_generated_sql_uses_controlled_fallback(database):
    result = await Text2SQLTool(database).invoke(
        {
            "sql": "DELETE FROM products",
            "filters": [
                {"field": "display_size_inch", "operator": "eq", "value": 27},
                {"field": "resolution", "operator": "eq", "value": "3840x2160"},
                {"field": "usb_c_video", "operator": "eq", "value": True},
            ],
            "reason": "组合筛选",
        }
    )
    assert result.status == "degraded"
    assert result.data["fallback_used"] is True
    assert {row["model_id"] for row in result.data["rows"]} == {
        "dell-u2723qe-cn", "dell-s2722qc-cn", "asus-pa279crv-cn", "lg-27up850k-w-cn",
        "benq-pd2705u-us", "benq-pd2725u-ca",
    }


@pytest.mark.asyncio
async def test_resolution_alias_is_normalized_in_fallback(database):
    result = await Text2SQLTool(database).invoke(
        {
            "sql": "SELECT model_id FROM products WHERE resolution='QHD' AND refresh_rate_hz>=120 "
            "AND is_oled=0 AND has_usb_c=0",
            "filters": [
                {"field": "resolution", "operator": "eq", "value": "QHD"},
                {"field": "refresh_rate_hz", "operator": "gte", "value": 120},
                {"field": "is_oled", "operator": "eq", "value": False},
                {"field": "has_usb_c", "operator": "eq", "value": False},
            ],
            "reason": "QHD 组合筛选",
        }
    )
    assert result.status == "degraded"
    assert [row["model_id"] for row in result.data["rows"]] == ["dell-g2724d-cn"]
