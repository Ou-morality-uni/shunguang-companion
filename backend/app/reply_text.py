"""Hide standalone, non-executable tool markup without touching fenced examples."""

import re

TOOL_FAILURE = '这次文件操作没有执行：模型未返回有效的工具调用，请重新发送请求。'


class ReplyText:
    def __init__(self):
        self.prefix = ''
        self.ordinary = False
        self.fence = ''
        self.tool = False
        self.tail = ''
        self.leaked = False

    def push(self, text):
        output = ''
        for char in text:
            if self.tool:
                self.tail = (self.tail + char)[-12:]
                if self.tail.lower().endswith('</tool_call>'):
                    self.tool = False
                    self.tail = ''
                continue
            if self.ordinary:
                output += char
                if char == '\n':
                    self.ordinary = False
                continue
            self.prefix += char
            if char == '\n':
                match = re.fullmatch(r' {0,3}(`{3,}|~{3,})([^\n]*)\n', self.prefix)
                if match:
                    marker = match[1]
                    if not self.fence:
                        self.fence = marker
                    elif marker[0] == self.fence[0] and len(marker) >= len(self.fence) and not match[2].strip():
                        self.fence = ''
                output += self.prefix
                self.prefix = ''
                continue
            stripped = self.prefix.lstrip(' ')
            indented = len(self.prefix) - len(stripped) > 3
            if not indented and (stripped in ('', '`', '``', '~', '~~') or stripped.startswith(('```', '~~~'))):
                continue
            if not self.fence and not indented and '<tool_call>'.startswith(stripped.lower()):
                if stripped.lower() == '<tool_call>':
                    self.prefix = ''
                    self.tool = True
                    self.leaked = True
                    output += TOOL_FAILURE
                continue
            output += self.prefix
            self.prefix = ''
            self.ordinary = True
        return output

    def finish(self):
        if not self.fence and self.prefix.lstrip().lower().startswith('<tool_'):
            self.leaked = True
            tail = TOOL_FAILURE
        else:
            tail = self.prefix
        self.prefix = ''
        return tail
