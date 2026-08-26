from __future__ import annotations

from smartbuy.retrieval.knowledge_base import REQUIRED_CHUNK_METADATA, load_fact_card_documents


def test_fact_cards_produce_metadata_complete_documents(monkeypatch) -> None:
    monkeypatch.setenv("UTU_LLM_MODEL", "qwen-plus")
    monkeypatch.setenv("UTU_LLM_TYPE", "chat.completions")

    documents = load_fact_card_documents()

    assert len(documents) == 60
    assert len({document.id for document in documents}) == len(documents)
    assert all(REQUIRED_CHUNK_METADATA <= set(document.metadata or {}) for document in documents)
    assert {document.metadata["embedding_dimensions"] for document in documents} == {1024}


def test_no_secret_is_required_in_fact_card_loader(monkeypatch) -> None:
    monkeypatch.delenv("Qianwen_api_key", raising=False)
    monkeypatch.setenv("UTU_LLM_MODEL", "qwen-plus")
    monkeypatch.setenv("UTU_LLM_TYPE", "chat.completions")

    assert load_fact_card_documents({"dell-u2723qe-cn"})
