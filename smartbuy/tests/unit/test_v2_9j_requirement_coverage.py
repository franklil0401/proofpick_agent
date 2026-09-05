"""Development regressions for raw user requirements, independent of model output."""

from types import SimpleNamespace

import pytest

from smartbuy.agent import PurchaseDecisionAgent
from smartbuy.constraints import ConstraintNormalizer
from smartbuy.db.build_database import build_database
from smartbuy.tools import EvidenceCheckTool, Text2SQLTool, WebSearchTool


class NoCalls:
    calls = 0
    schema = {"type": "function", "function": {"name": "kb_search"}}

    async def chat(self, *args, **kwargs):
        self.calls += 1
        return SimpleNamespace(data={"role": "assistant", "content": ""})

    async def invoke(self, arguments):
        raise AssertionError("unresolved requirements must pause before retrieval")


@pytest.fixture
def agent(tmp_path):
    database = tmp_path / "catalog.sqlite"
    build_database(database)
    provider = NoCalls()
    return PurchaseDecisionAgent(provider, {
        "text2sql": Text2SQLTool(database), "kb_search": provider,
        "evidence_check": EvidenceCheckTool(database), "web_search": WebSearchTool(),
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "筛选刷新率至少144Hz，机身宽度最多半米的显示器。",
    "筛选刷新率至少144Hz，机身宽度最多610furlong。",
    "挑选刷新率至少144Hz，机身宽度窄一点。",
    "筛选机身宽度最多610mm且最少某个下限。",
])
async def test_unresolved_explicit_requirement_pauses_before_paid_tools(agent, query):
    report = await agent.run(query)
    assert report.clarification_state.value == "pending"
    assert report.recommended_model_ids == []
    assert agent.provider.calls == 0
    assert report.tool_call_count == 0
    assert report.usage["requirement_coverage"]["complete"] is False


@pytest.mark.asyncio
async def test_missing_one_of_two_requirements_cannot_pass_with_partial_constraint_set(agent):
    class DropWidth(ConstraintNormalizer):
        def build(self, *args, **kwargs):
            result = super().build(*args, **kwargs)
            result.constraints = [x for x in result.constraints if x.field != "width_mm"]
            return result

    agent.constraint_normalizer = DropWidth()
    report = await agent.run("筛选刷新率至少144Hz，机身宽度最多610mm。")
    assert report.clarification_state.value == "pending"
    assert report.recommended_model_ids == []
    assert agent.provider.calls == 0
