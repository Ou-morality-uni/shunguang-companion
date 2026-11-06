from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 16000
TERMINAL = {'complete', 'failed', 'cancelled', 'interrupted', 'restored'}
BLOCKED = {'.git', '.codex', '.agents', '.aws', '.ssh', '.venv', '.venv-rag', 'node_modules'}


class WorkError(Exception):
    def __init__(self, message, status=409):
        self.message, self.status = message, status
        super().__init__(message)


class TaskCancelled(Exception):
    pass


class WorkPause(Exception):
    pass


class FileStep(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['list', 'read', 'write', 'move', 'delete', 'read_document']
    path: str = Field(default='.', min_length=1, max_length=500)
    destination: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, max_length=200000)
    start: int = Field(default=1, ge=1, le=1000000)
    limit: int = Field(default=20, ge=1, le=50)
    visual: bool = False
    scope: Literal['range', 'full', 'focused'] = 'range'
    query: str = Field(default='', max_length=300)

    @model_validator(mode='after')
    def operation_fields(self):
        if (self.action == 'move') != (self.destination is not None):
            raise ValueError('只有移动操作需要目标路径')
        if (self.action == 'write') != (self.content is not None):
            raise ValueError('只有写入操作需要完整文本内容')
        return self


class FileTaskRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    workspace_id: str = Field(min_length=1, max_length=80)
    title: str = Field(default='文件任务', min_length=1, max_length=120)
    steps: list[FileStep] = Field(min_length=1, max_length=50)
    instruction: str = Field(default='', max_length=4000)
    save_result: bool = False

    @model_validator(mode='after')
    def bounded_content(self):
        if sum(len(step.content or '') for step in self.steps) > 1000000:
            raise ValueError('任务文本总量过大')
        if self.instruction and not any(step.action == 'read_document' for step in self.steps):
            raise ValueError('阅读要求需要至少一个文档阅读步骤')
        return self
