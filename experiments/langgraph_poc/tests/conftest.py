from __future__ import annotations

import pytest

from smartbuy.db.build_database import build_database

from experiments.langgraph_poc.graph import LangGraphPoc


@pytest.fixture()
def database(tmp_path):
    path = tmp_path / "poc-catalog.sqlite"
    build_database(path)
    return path


@pytest.fixture()
def poc(database):
    return LangGraphPoc(database)
