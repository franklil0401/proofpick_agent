"""Tests for configuration response redaction."""

import os


# Importing the upstream ``utu`` package constructs model config at module
# import time. Keep this security unit test self-contained and credential-free.
os.environ.setdefault("UTU_LLM_MODEL", "stage1-test-model")
os.environ.setdefault("UTU_LLM_TYPE", "chat.completions")

from utu.rag.api.utils.security import REDACTED_VALUE, redact_sensitive_config


def test_redact_sensitive_config_recursively_without_mutating_source():
    source = {
        "embedding": {"api_key": "dummy-api-key", "model": "test-model"},
        "connections": [
            {"password": "dummy-password", "endpoint": "https://example.test"},
            {"nested_token": "dummy-token"},
        ],
        "MINIO_ACCESS_KEY": "dummy-access-key",
        "authorization_header": "Bearer dummy-token",
        "empty_secret": "",
        "token_count": 42,
    }

    result = redact_sensitive_config(source)

    assert result["embedding"]["api_key"] == REDACTED_VALUE
    assert result["embedding"]["model"] == "test-model"
    assert result["connections"][0]["password"] == REDACTED_VALUE
    assert result["connections"][1]["nested_token"] == REDACTED_VALUE
    assert result["MINIO_ACCESS_KEY"] == REDACTED_VALUE
    assert result["authorization_header"] == REDACTED_VALUE
    assert result["empty_secret"] == ""
    assert result["token_count"] == 42
    assert source["embedding"]["api_key"] == "dummy-api-key"
