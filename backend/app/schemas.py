"""Public contracts. Exported to TypeScript by scripts/export-openapi.py."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from .constants import MAX_MESSAGE_LENGTH


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class SourceOut(BaseModel):
    id: str | None = None
    number: int | None = None
    title: str | None = None
    text: str | None = None
    snippet: str | None = None
    url: str | None = None
    source_url: str | None = None
    document_id: str | None = None
    verification_status: str | None = None
    spoiler: str | bool | None = None
    version: str | None = None
    score: float | None = None


class ToolEventOut(BaseModel):
    id: str | None = None
    name: str | None = None
    tool: str | None = None
    status: str | None = None
    message: str | None = None
    result: Any = None
    arguments: Any = None


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: Literal['user', 'assistant']
    content: str
    status: Literal['complete', 'streaming', 'interrupted', 'error']
    created_at: str
    seq: int | None = None
    sources: list[SourceOut] = Field(default_factory=list)
    tools: list[ToolEventOut] = Field(default_factory=list)


class SettingsOut(BaseModel):
    base_url: str
    model: str
    temperature: float
    timeout: float
    max_tokens: int
    has_api_key: bool
    configured: bool
    provider: str
    protocol: Literal['openai', 'anthropic']


class CapabilitiesOut(BaseModel):
    max_message_length: int = MAX_MESSAGE_LENGTH


class MemoryOut(BaseModel):
    id: str
    key: str
    value: str
    source_message_id: str | None = None
    created_at: str
    updated_at: str
