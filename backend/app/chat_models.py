from pydantic import BaseModel, Field, field_validator

from .constants import MAX_MESSAGE_LENGTH
from .model_choices import ModelChoice


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    attachments: list[str] = Field(default_factory=list, max_length=10)
    model_choice: ModelChoice | None = None
    annotations: list[str] = Field(default_factory=list, max_length=30)
    annotation_scope: str = Field(default='', max_length=80)

    @field_validator('content')
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('消息不能为空')
        return value.strip()
