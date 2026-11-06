"""Conservative request budgeting; estimates are not provider tokenizer counts."""

import json

from langchain_core.messages import SystemMessage


class ContextBudgetError(ValueError):
    pass


def estimated_tokens(messages, schemas):
    # Approximate two UTF-8 bytes per token, conservative for ordinary Chinese/Latin.
    # Custom tokenizers can differ; the configurable budget is not a provider guarantee.
    payload = [
        {
            'role': message.type,
            'content': message.content,
            'tool_calls': getattr(message, 'tool_calls', []),
            'tool_call_id': getattr(message, 'tool_call_id', None),
        }
        for message in messages
    ]
    return (len(json.dumps([payload, schemas], ensure_ascii=False).encode('utf-8')) + 1) // 2 + 256


def fit_context(messages, schemas, budget, protected_from):
    """Drop old reference/history prefixes; never split the active tool exchange."""
    rules = [item for item in messages[:protected_from] if isinstance(item, SystemMessage)]
    older = [item for item in messages[:protected_from] if not isinstance(item, SystemMessage)]
    active = messages[protected_from:]
    while older and estimated_tokens(rules + older + active, schemas) > budget:
        older.pop(0)
        # A retained prefix must not begin with an assistant/tool reply without its user.
        while older and older[0].type not in ('human', 'system'):
            older.pop(0)
    result = rules + older + active
    if estimated_tokens(result, schemas) > budget:
        raise ContextBudgetError('本轮内容超过上下文预算，请缩短消息、减少附件或调大模型上下文预算。')
    return result
