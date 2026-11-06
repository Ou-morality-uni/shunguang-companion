import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from backend.app.context_budget import fit_context


def test_budget_removes_old_turn_without_splitting_current_tool_exchange():
    messages = [
        SystemMessage('rules'),
        HumanMessage('old' * 4000),
        AIMessage('old answer'),
        HumanMessage('current question'),
        AIMessage(content='', tool_calls=[{'id': '1', 'name': 'lookup', 'args': {}}]),
        ToolMessage(content='result', tool_call_id='1'),
    ]
    result = fit_context(messages, [], 2000, 3)
    assert [message.content for message in result] == ['rules', 'current question', '', 'result']


def test_oversized_current_request_is_rejected_without_truncation():
    from backend.app.context_budget import ContextBudgetError

    with pytest.raises(ContextBudgetError, match='上下文预算'):
        fit_context([SystemMessage('rules'), HumanMessage('x' * 4000)], [], 2000, 1)


def test_tool_schema_is_included_in_request_budget():
    from backend.app.context_budget import ContextBudgetError

    with pytest.raises(ContextBudgetError):
        fit_context([SystemMessage('rules'), HumanMessage('question')], [{'description': 'x' * 4000}], 2000, 1)
