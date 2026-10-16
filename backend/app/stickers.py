"""In-turn scene hints and allowlisted red-persona reactions; no extra model call."""

import hashlib
import json
import re

from . import config

PREFIX = '[[sticker:'
CONTROL_START = re.compile(re.escape(PREFIX), re.IGNORECASE | re.ASCII)
NEUTRAL = (
    ('49-red-daily-by-your-side.png', '在呢，陪着你'),
    ('33-red-daily-sit-together.png', '陪你坐会儿'),
    ('22-red-daily-listening.png', '你说，我听着'),
)


def load_catalog():
    directory = config.ROOT / 'source/resources/character/stickers'
    try:
        catalog = json.loads((directory / 'reactions.json').read_text(encoding='utf-8'))
        scenes = catalog['scenes']
        if not isinstance(scenes, dict) or 'neutral' not in scenes:
            raise ValueError('invalid sticker scenes')
        items = [
            item
            for item in catalog['items']
            if item.get('persona') == 'red'
            and re.fullmatch(r'[a-zA-Z0-9-]+\.png', item.get('file', ''))
            and re.fullmatch(r'[a-zA-Z0-9-]+', item.get('id', ''))
            and isinstance(item.get('caption'), str)
            and isinstance(item.get('scenes'), list)
            and any(scene in scenes for scene in item['scenes'])
            and (directory / item['file']).is_file()
        ]
        if not items or not any('neutral' in item['scenes'] for item in items):
            raise ValueError('empty sticker catalog')
        return {'scenes': scenes, 'items': items}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # A broken optional catalog must not turn a successful chat into an error.
        return {
            'scenes': {'neutral': '通用、安静陪伴'},
            'items': [
                {'id': file[:-4], 'file': file, 'caption': caption, 'persona': 'red', 'scenes': ['neutral']}
                for file, caption in NEUTRAL
                if (directory / file).is_file()
            ],
        }


def instruction(catalog):
    scenes = '；'.join(f'{key}={description}' for key, description in catalog['scenes'].items())
    return (
        '\n展示规则：结合本轮用户情绪、近期对话和你的最终回答，选择一个贴切的表情场景。'
        '以本轮为准，不沿用已结束的话题或旧情绪；用户倾诉难过时选择安慰/倾听，不要庆祝或撒娇。'
        '没有合适场景或在认真解释事情时选 neutral。最终回复必须先输出一个场景控制标记，'
        '紧接着再写自然回答，格式如 [[sticker:comfort]]我在，慢慢说。不要省略标记，不要用代码块包裹。'
        '标记是协议字段，由界面移除，用户不会看到或听到它，因此不违反自然表达要求。不要解释它，'
        '不输出图片路径、图片链接或多个标记，不把标记放进工具参数。可选场景：' + scenes
    )


class ReplyDecoration:
    """Strip scene controls before text reaches SSE, TTS or stored history.

    Only possible control prefixes are held back; ordinary prose streams at once.
    Unknown hints and truncated controls fall back to neutral without leaking.
    """

    def __init__(self):
        self.pending = ''
        self.inside = False
        self.hint = ''
        self.overflow = False

    def push(self, text):
        self.pending += text
        visible = ''
        while self.pending:
            if self.inside:
                end = self.pending.find(']]')
                newline = self.pending.find('\n')
                if end >= 0 and (newline < 0 or end < newline):
                    value = self.pending[:end].strip().lower()
                    self.hint = value if not self.overflow and re.fullmatch(r'[a-z_]{1,32}', value) else ''
                    self.pending = self.pending[end + 2 :]
                    self.inside = False
                    continue
                if newline >= 0:
                    self.hint = ''
                    self.pending = self.pending[newline:]
                    self.inside = False
                    continue
                if len(self.pending) > 128:
                    self.overflow = True
                    self.pending = self.pending[-1:] if self.pending.endswith(']') else ''
                break
            match = CONTROL_START.search(self.pending)
            if match:
                start = match.start()
                visible += self.pending[:start]
                self.pending = self.pending[start + len(PREFIX) :]
                self.inside = True
                self.hint = ''
                self.overflow = False
                continue
            held = next(
                (size for size in range(len(PREFIX) - 1, 0, -1) if self.pending[-size:].lower() == PREFIX[:size]), 0
            )
            visible += self.pending[:-held] if held else self.pending
            self.pending = self.pending[-held:] if held else ''
            break
        return visible

    def finish(self):
        # Preserve ordinary trailing brackets, but never expose a partial control.
        tail = self.pending if not self.inside and len(self.pending) <= 2 else ''
        self.pending = ''
        self.inside = False
        return tail


def choose(catalog, hint, history, seed):
    scene = hint if hint in catalog['scenes'] else 'neutral'
    neutral = [item for item in catalog['items'] if 'neutral' in item['scenes']]
    candidates = [item for item in catalog['items'] if scene in item['scenes']]
    if not candidates:
        candidates, scene = neutral, 'neutral'
    recent = [
        message['sticker']['id']
        for message in reversed(history)
        if message.get('role') == 'assistant'
        and isinstance(message.get('sticker'), dict)
        and message['sticker'].get('id')
    ][:3]
    # Preserve the meaning first; when a sole match repeats, use a neutral image.
    fresh = [item for item in candidates if item['id'] not in recent]
    non_repeating = [item for item in candidates if not recent or item['id'] != recent[0]]
    if fresh:
        candidates = fresh
    elif non_repeating:
        candidates = non_repeating
    elif recent:
        alternatives = [item for item in neutral if item['id'] != recent[0]]
        if alternatives:
            candidates, scene = alternatives, 'neutral'
    if not candidates:
        return None
    item = candidates[int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(candidates)]
    return {
        'id': item['id'],
        'url': '/api/resources/character/stickers/' + item['file'],
        'caption': item['caption'],
        'persona': 'red',
        'scene': scene,
    }
