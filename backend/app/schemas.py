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
    usage: str | None = None
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


class StickerOut(BaseModel):
    id: str
    url: str
    caption: str
    persona: Literal['red']
    scene: str


class HistorySourceOut(BaseModel):
    message_id: str
    conversation_id: str
    title: str
    role: Literal['user', 'assistant']
    time: str
    text: str
    episode_summary: str | None = None


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: Literal['user', 'assistant']
    content: str
    status: Literal['complete', 'streaming', 'interrupted', 'error']
    created_at: str
    seq: int | None = None
    sources: list[SourceOut] = Field(default_factory=list)
    context_sources: list[SourceOut] = Field(default_factory=list)
    tools: list[ToolEventOut] = Field(default_factory=list)
    sticker: StickerOut | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    history_sources: list[HistorySourceOut] = Field(default_factory=list)
    annotations: list[dict[str, Any]] = Field(default_factory=list)


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
    vision: Literal['unknown', 'supported', 'unsupported'] = 'unknown'
    effort: str = 'default'
    efforts: list[str] = Field(default_factory=lambda: ['default'])


class CapabilitiesOut(BaseModel):
    max_message_length: int = MAX_MESSAGE_LENGTH


class WorkspaceOut(BaseModel):
    id: str
    path: str
    enabled: bool
    created_at: str


class FileStepOut(BaseModel):
    action: Literal['list', 'read', 'write', 'move', 'delete', 'read_document', 'summarize', 'upload', 'office']
    path: str
    destination: str | None = None
    state: str
    result: dict[str, Any] | None = None
    vision_request: dict[str, Any] | None = None


class FileTaskOut(BaseModel):
    can_retry_summary: bool = False
    id: str
    workspace_id: str
    title: str
    status: Literal[
        'queued',
        'running',
        'waiting_approval',
        'waiting_vision',
        'waiting_limit',
        'waiting_output',
        'complete',
        'failed',
        'cancelled',
        'interrupted',
        'restoring',
        'restored',
    ]
    steps: list[FileStepOut]
    error: str
    created_at: str
    updated_at: str
    can_restore: bool
    origin: Literal['workbench', 'chat'] = 'workbench'
    events: list[dict[str, Any]] = Field(default_factory=list)
    conversation_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class MemoryOut(BaseModel):
    id: str
    key: str
    value: str
    source_message_id: str | None = None
    created_at: str
    updated_at: str


class DocumentUploadOut(BaseModel):
    workspace: WorkspaceOut
    path: str
    task: FileTaskOut


class CloudVoiceOut(BaseModel):
    voice: str
    name: str
    model: str
    created_at: str = ''
    status: str = 'OK'


class CloudVoiceListOut(BaseModel):
    voices: list[CloudVoiceOut]
    model: str
    selected: str


class CloudVoiceCreatedOut(BaseModel):
    voice: str
    model: str
    features: dict[str, Any]
    fallback_mode: bool = False
    reused: bool = False
