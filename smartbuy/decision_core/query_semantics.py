"""Shared, catalog-free task intent signals with clause-scoped negation.

This module grants no product identity, field value or tool permission. It only
distinguishes an affirmative action request from an action mentioned inside a
negative instruction; consumers still validate constraints and candidate scope.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


_PURCHASE = re.compile(r"筛选|筛出|挑选|选购|推荐")
_COMPARISON = re.compile(r"比较|对比|对照|区分|差别|差异|有何不同|不同|是否等同|是不是同")
_FACT = re.compile(r"核验|核实|核对|查询|请查|只查|查一下|给证据|提供证据|是什么|多少|分别是|支持哪些")
_ASK_FIRST = re.compile(
    r"先(?:向我|跟我|和我|让我|请你)?(?:询问|问|确认|澄清)"
    r"|(?:问清楚|澄清|确认)(?:用途|条件|地区|型号|版本|配置)?(?:以后|之后|后)再"
)
_NEGATION = re.compile(
    r"不要|不得|不能|不许|不必(?!要)|不用|无需|无须|不需要|不想|不愿|不希望"
    r"|不是|并非|拒绝|禁止|(?<![差分区类识鉴级])别|不把|不将|不让|不(?:向|给|为)我|不$"
)
_DOUBLE_NEGATION = re.compile(r"(?:并非|不是)(?:说|表示)?\s*(?:不要|不必|不需要|不想|不愿|不)")
_ACTION = re.compile("|".join(pattern.pattern for pattern in (_PURCHASE, _COMPARISON, _FACT, _ASK_FIRST)))
_NEGATIVE_ACTION_INTRO = re.compile(
    r"(?:不要|不得|不能|不许|不用|无需|无须|不需要|不想|不愿|不希望|别)"
    r"\s*(?:你|您)?\s*(?:把|将|让|使|根据|依据|基于|参考|使用)"
    r"|不(?:把|将|让)"
)
_NEW_ACTION_REQUEST = re.compile(
    r"^\s*(?:请(?:你)?|直接|帮我|给我|替我)\s*"
    r"(?:(?:只|仅|先|再|帮我|给我|替我)\s*)?(?:" + _ACTION.pattern + r")"
)
_PARENTHETICAL_OBJECT = re.compile(r"^\s*(?:尤其|特别是|包括|例如|比如|其中|也就是|即)")


@dataclass(frozen=True)
class TrustedQueryIntentSignals:
    purchase_requested: bool = False
    purchase_forbidden: bool = False
    comparison_requested: bool = False
    fact_requested: bool = False
    ask_first: bool = False

    @property
    def task_type(self) -> str | None:
        if self.ask_first:
            return "clarification"
        if self.purchase_requested:
            return "filter"
        if self.comparison_requested:
            return "comparison"
        if self.fact_requested or self.purchase_forbidden:
            return "fact"
        return None


def _negated(prefix: str) -> bool:
    # A scoped double denial is not an instruction to suppress the action.
    # Ordinary negative product properties (e.g. 不超过) are not action negators.
    return bool(_NEGATION.search(_DOUBLE_NEGATION.sub("", prefix)))


def _action_clauses(text: str):
    # A comma may surround a parenthetical object, not finish an instruction:
    # “不要把这些对象，尤其是相近条目，标成推荐商品”. Carry only an
    # unfinished negative *action* introduction; a property such as “不要 OLED”
    # must not poison the next affirmative request. A completed predicate, an
    # explicit new imperative, a sentence end or contrast ends this scope.
    for sentence in re.split(r"[。；;!?？！\n]+|但是|不过|然而|而是|但", text):
        pending = ""
        for fragment in re.split(r"[，,]+", sentence):
            if pending and _NEW_ACTION_REQUEST.search(fragment):
                yield pending
                pending = ""
            if pending:
                pending += "," + fragment
                # “尤其是参数存在差异的条目” describes the object; its
                # comparison noun does not complete the pending predicate.
                if _ACTION.search(fragment) and not _PARENTHETICAL_OBJECT.search(fragment):
                    yield pending
                    pending = ""
            elif _NEGATIVE_ACTION_INTRO.search(_DOUBLE_NEGATION.sub("", fragment)) and not _ACTION.search(fragment):
                pending = fragment
            else:
                yield fragment
        if pending:
            yield pending


def analyze_trusted_query_intent(query: str) -> TrustedQueryIntentSignals:
    text = unicodedata.normalize("NFKC", query).casefold()
    # Keep the enumeration separator 、 inside the clause: the negated object
    # may include a list of fields before its action verb. Contrast introduces
    # a new action scope, so “不要推荐，但请筛选” keeps the latter request.
    positive = {"purchase": False, "comparison": False, "fact": False, "ask": False}
    purchase_forbidden = False
    for clause in _action_clauses(text):
        for kind, pattern in (("purchase", _PURCHASE), ("comparison", _COMPARISON), ("fact", _FACT), ("ask", _ASK_FIRST)):
            for found in pattern.finditer(clause):
                negated = _negated(clause[:found.start()])
                if kind == "purchase" and negated:
                    purchase_forbidden = True
                if not negated:
                    positive[kind] = True
    return TrustedQueryIntentSignals(
        purchase_requested=positive["purchase"], purchase_forbidden=purchase_forbidden,
        comparison_requested=positive["comparison"], fact_requested=positive["fact"],
        ask_first=positive["ask"],
    )
