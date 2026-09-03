from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from smartbuy.api.router import _domain_memories, router


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("PROOFPICK_V2_MEMORY_PATH", str(tmp_path / "runtime-memory"))
    _domain_memories.clear()
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_v2_memory_api_global_category_lifecycle_and_user_isolation(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    headers = {"X-ProofPick-Identity": "user-a"}
    saved_global = client.put(
        "/api/smartbuy/memory/user-a",
        json={
            "domain_id": "monitor",
            "scope": "global",
            "preferences": {"excluded_brands": ["Dell"]},
            "explicitly_confirmed": True,
        },
        headers=headers,
    )
    assert saved_global.status_code == 200
    saved_category = client.put(
        "/api/smartbuy/memory/user-a",
        json={
            "domain_id": "laptop",
            "scope": "category",
            "preferences": {"ranking_scenario": "portability"},
            "explicitly_confirmed": True,
        },
        headers=headers,
    )
    assert saved_category.status_code == 200
    viewed = client.get(
        "/api/smartbuy/memory/user-a", params={"domain_id": "laptop"}, headers=headers
    ).json()
    assert viewed["effective_preferences"] == {
        "excluded_brands": ["Dell"],
        "ranking_scenario": "portability",
    }
    assert client.get(
        "/api/smartbuy/memory/user-b", params={"domain_id": "laptop"}, headers=headers
    ).status_code == 403
    assert client.put(
        "/api/smartbuy/memory/user-b",
        json={
            "domain_id": "laptop",
            "preferences": {"ranking_scenario": "gaming"},
            "explicitly_confirmed": True,
        },
        headers=headers,
    ).status_code == 403
    assert client.request(
        "DELETE",
        "/api/smartbuy/memory/user-b",
        json={"domain_id": "laptop", "scope": "category", "fields": None},
        headers=headers,
    ).status_code == 403
    assert client.get(
        "/api/smartbuy/memory/user-b",
        params={"domain_id": "laptop"},
        headers={"X-ProofPick-Identity": "user-b"},
    ).json()["effective_preferences"] == {}
    disabled = client.post(
        "/api/smartbuy/memory/user-a/enabled",
        json={"domain_id": "laptop", "enabled": False},
        headers=headers,
    )
    assert disabled.json()["enabled"] is False
    enabled = client.post(
        "/api/smartbuy/memory/user-a/enabled",
        json={"domain_id": "laptop", "enabled": True},
        headers=headers,
    )
    assert enabled.json()["enabled"] is True
    deleted = client.request(
        "DELETE",
        "/api/smartbuy/memory/user-a",
        json={"domain_id": "laptop", "scope": "category", "fields": None},
        headers=headers,
    )
    assert deleted.json()["category_preferences"] == {}


def test_v2_memory_api_rejects_unconfirmed_and_unknown_domain(
    tmp_path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    headers = {"X-ProofPick-Identity": "user"}
    unconfirmed = client.put(
        "/api/smartbuy/memory/user",
        json={
            "domain_id": "monitor",
            "preferences": {"ranking_scenario": "gaming"},
            "explicitly_confirmed": False,
        },
        headers=headers,
    )
    assert unconfirmed.status_code == 422
    unknown = client.get(
        "/api/smartbuy/memory/user", params={"domain_id": "camera"}, headers=headers
    )
    assert unknown.status_code == 422
