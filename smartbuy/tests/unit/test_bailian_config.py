from __future__ import annotations

import pytest

from smartbuy.config import BailianSettings, ConfigurationError, load_bailian_settings


def test_loads_only_expected_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("Qianwen_api_key", "placeholder-credential")
    monkeypatch.setenv("Qianwen_workspace_id", "ws-placeholder123")

    settings = load_bailian_settings()

    assert settings.availability() == {
        "Qianwen_api_key": "configured",
        "Qianwen_workspace_id": "configured",
    }
    assert "placeholder-credential" not in repr(settings)
    assert settings.embedding_dimensions == 1024
    assert settings.rerank_url.endswith("/compatible-api/v1/reranks")


def test_missing_key_fails_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("Qianwen_api_key", raising=False)
    monkeypatch.setenv("Qianwen_workspace_id", "ws-placeholder123")

    with pytest.raises(ConfigurationError, match="missing"):
        load_bailian_settings()


def test_invalid_workspace_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="invalid format"):
        BailianSettings(api_key="placeholder", workspace_id="https://invalid.example")
