import json

import pytest

from backend.app import config, stickers


def test_catalog_uses_all_44_red_images_including_30_new_daily_images():
    catalog = stickers.load_catalog()
    assert len(catalog['items']) == 44
    assert len({item['id'] for item in catalog['items']}) == 44
    assert all(item['persona'] == 'red' and 'white' not in item['file'] for item in catalog['items'])
    assert sum('-red-daily-' in item['file'] for item in catalog['items']) == 30
    assert all(set(item['scenes']) <= catalog['scenes'].keys() for item in catalog['items'])
    neutral = [item for item in catalog['items'] if 'neutral' in item['scenes']]
    assert {item['caption'] for item in neutral} == {'你说，我听着', '陪你坐会儿', '在呢，陪着你'}


def test_missing_or_unsafe_catalog_cannot_break_chat_or_select_an_external_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    directory = tmp_path / 'source/resources/character/stickers'
    directory.mkdir(parents=True)
    for content in (
        'broken json',
        json.dumps(
            {
                'scenes': {'neutral': '陪伴'},
                'items': [
                    {
                        'id': 'external',
                        'file': '../../avatar.png',
                        'caption': 'bad',
                        'persona': 'red',
                        'scenes': ['neutral'],
                    }
                ],
            }
        ),
    ):
        (directory / 'reactions.json').write_text(content, encoding='utf-8')
        catalog = stickers.load_catalog()
        assert stickers.choose(catalog, 'neutral', [], 'seed') is None


def test_catalog_without_neutral_entries_recovers_existing_neutral_images(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    directory = tmp_path / 'source/resources/character/stickers'
    directory.mkdir(parents=True)
    file, caption = stickers.NEUTRAL[0]
    (directory / file).touch()
    (directory / 'reactions.json').write_text(
        json.dumps({'scenes': {'neutral': '陪伴'}, 'items': []}), encoding='utf-8'
    )
    result = stickers.choose(stickers.load_catalog(), 'unknown', [], 'seed')
    assert result['caption'] == caption and result['scene'] == 'neutral'


@pytest.mark.parametrize('hint', ['comfort', 'neutral', 'rain', 'https://invalid.example/pic.png'])
@pytest.mark.parametrize('position', ['prefix', 'suffix'])
def test_control_never_leaks_at_any_stream_split(hint, position):
    body, tag = '先坐一会儿吧。[1]\n', f'[[sticker:{hint}]]'
    raw = tag + body if position == 'prefix' else body + tag
    for split in range(len(raw) + 1):
        decoration = stickers.ReplyDecoration()
        visible = decoration.push(raw[:split]) + decoration.push(raw[split:]) + decoration.finish()
        assert visible == '先坐一会儿吧。[1]\n'
        assert decoration.hint == (hint if hint.isalpha() else '')
    decoration = stickers.ReplyDecoration()
    assert ''.join(decoration.push(char) for char in raw) + decoration.finish() == '先坐一会儿吧。[1]\n'


def test_missing_truncated_and_malformed_controls_use_safe_fallback_without_losing_markdown():
    for raw, expected in [
        ('普通回答，包含 [1] 和 [链接](https://example.com)。', '普通回答，包含 [1] 和 [链接](https://example.com)。'),
        ('保留左括号[', '保留左括号['),
        ('不用着急。[[sticker:com', '不用着急。'),
        ('不用着急。[[stick', '不用着急。'),
        ('先听你说。[[sticker:bad\n后续正文', '先听你说。\n后续正文'),
    ]:
        decoration = stickers.ReplyDecoration()
        assert ''.join(decoration.push(char) for char in raw) + decoration.finish() == expected
        assert decoration.hint == ''


def test_reply_with_only_a_control_is_empty_and_does_not_fabricate_prose():
    decoration = stickers.ReplyDecoration()
    assert decoration.push('[[sticker:comfort]]') + decoration.finish() == ''


def test_case_variations_and_oversized_controls_are_filtered_and_bounded():
    decoration = stickers.ReplyDecoration()
    raw = '先听你说。[[StIcKeR:COMFORT]]'
    assert ''.join(decoration.push(char) for char in raw) + decoration.finish() == '先听你说。'
    assert decoration.hint == 'comfort'
    decoration = stickers.ReplyDecoration()
    assert decoration.push('[[sticker:' + 'x' * 1000) == ''
    assert len(decoration.pending) <= 128
    assert decoration.push('comfort]]正文') + decoration.finish() == '正文'
    assert decoration.hint == ''


def test_known_scenes_select_relevant_red_images_and_invalid_scenes_use_neutral():
    catalog = stickers.load_catalog()
    for scene in catalog['scenes']:
        result = stickers.choose(catalog, scene, [], 'message-id')
        item = next(item for item in catalog['items'] if item['id'] == result['id'])
        assert scene in item['scenes']
        assert result['persona'] == 'red'
        assert result['url'].startswith('/api/resources/character/stickers/')
    for hint in ('', 'invented_scene', '../../outside.png'):
        assert stickers.choose(catalog, hint, [], 'message-id')['scene'] == 'neutral'


def test_rotation_survives_history_reload_without_replacing_meaning_with_another_emotion():
    catalog = stickers.load_catalog()
    history = []
    for number in range(12):
        result = stickers.choose(catalog, 'neutral', history, str(number))
        if history:
            assert result['id'] != history[-1]['sticker']['id']
        if number < 3:
            assert result['id'] not in [message['sticker']['id'] for message in history]
        history.append({'role': 'assistant', 'sticker': result})
        assert result == stickers.choose(catalog, 'neutral', history[:-1], str(number))
    first = stickers.choose(catalog, 'rain', [], 'first')
    second = stickers.choose(catalog, 'rain', [{'role': 'assistant', 'sticker': first}], 'second')
    assert first['id'] != second['id'] and second['scene'] == 'neutral'


def test_instruction_explains_current_context_and_neutral_fallback_without_image_urls():
    prompt = stickers.instruction(stickers.load_catalog())
    assert '本轮用户情绪' in prompt and 'neutral' in prompt
    assert '不要庆祝或撒娇' in prompt
    assert '/api/resources/' not in prompt
