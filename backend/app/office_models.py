"""Typed Office tasks share the existing queue and authorized artifact journal."""

import json
from pathlib import PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .office_overwrite import OverwriteTarget


class ResourceRef(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['attachment', 'artifact']
    id: str = Field(min_length=1, max_length=100)
    version: str = Field(pattern=r'^[0-9a-f]{64}$')


class OfficeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    format: Literal['docx', 'xlsx', 'pdf', 'pptx', 'png', 'jpeg', 'webp']
    name: str = Field(min_length=1, max_length=120)
    operation: Literal['create', 'edit', 'export'] = 'create'
    source: ResourceRef | None = None
    conversation_id: str | None = Field(default=None, max_length=80)
    spec: dict | None = None
    instruction: str = Field(default='', max_length=6000)
    sources: list[ResourceRef] = Field(default_factory=list, max_length=10)
    export_pdf: bool = False
    outline: str = Field(default='', max_length=4000)
    overwrite: OverwriteTarget | None = None

    @model_validator(mode='after')
    def bounded(self):
        if self.format == 'xlsx' and isinstance(self.spec, dict):
            sheets = self.spec.get('sheets', [])
            nested = isinstance(sheets, list) and any(isinstance(sheet, dict) and 'edits' in sheet for sheet in sheets)
            if nested:
                raise ValueError(
                    'spec.sheets[].edits 不属于新建结构；请指定 source 并使用 operation=edit 和 spec.edits。'
                )
            if 'edits' in self.spec and self.operation == 'create' and self.source is None:
                raise ValueError('修改单元格必须明确指定 source 和 operation=edit，不能新建空表。')
        if (
            PureWindowsPath(self.name).name != self.name
            or any(character in self.name for character in '/\\:<>"|?*\x00')
            or not self.name.lower().endswith('.' + self.format)
            or self.name.endswith((' ', '.'))
            or PureWindowsPath(self.name).is_reserved()
            or any(ord(character) < 32 for character in self.name)
            or len(json.dumps(self.spec, ensure_ascii=False)) > 400000
            or (self.operation != 'create' and self.source is None)
            or (self.operation != 'export' and self.spec is None and not self.instruction.strip())
            or (self.export_pdf and self.format not in ('docx', 'xlsx', 'pptx'))
        ):
            raise ValueError('成果名称或内容无效')
        return self


GUIDES = {
    'docx': 'word',
    'xlsx': 'excel',
    'pdf': 'pdf',
    'pptx': 'ppt',
    'png': 'image',
    'jpeg': 'image',
    'webp': 'image',
}
