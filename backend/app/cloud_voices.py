"""Bailian voice lifecycle. Only metadata is persisted; reference audio is transient."""

import asyncio
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from threading import RLock

from . import config, feature_config, voice

LOCK = RLock()
MUTATIONS = asyncio.Lock()


def provider_error(error, stage='http'):
    # Provider prose can echo input. Classify internally; never return it verbatim.
    raw = (str(error.get('code', '')) + ' ' + str(error.get('message', ''))).lower() if isinstance(error, dict) else ''
    category, message = 'upstream', '百炼请求失败，请核对模型、音色和地域。'
    for words, code, description in [
        (
            ('invalid_api_key', 'invalidapikey', 'unauthorized', 'authentication'),
            'authentication',
            '百炼密钥无效或无访问权限。',
        ),
        (('quota', 'balance', 'arrear', 'credit'), 'quota', '百炼额度或账户余额受限，请在厂商后台核对。'),
        (('rate', 'throttl', 'limit'), 'rate_limit', '百炼请求频率受限，请稍后重试。'),
        (
            ('url', 'ossresource', 'download', 'resource resolve'),
            'reference_url',
            '百炼无法读取参考录音地址，请检查临时上传或提供可访问的录音 URL。',
        ),
        (
            ('no speech', 'audio quality', 'audio format', 'audio length', 'audio duration'),
            'reference_audio',
            '参考录音不符合复刻要求，请使用清晰单人语音并检查格式、时长与采样率。',
        ),
        (
            ('modelnot', 'model not', 'model_not', 'invalid model'),
            'model',
            '百炼拒绝了此模型，请核对当前地域的模型名称与调用权限。',
        ),
        (('voice', 'speaker'), 'voice', '百炼音色不可用，请刷新音色列表并检查绑定模型。'),
        (('model',), 'model', '百炼模型不可用，请检查模型名称和权限。'),
    ]:
        if any(word in raw for word in words):
            category, message = code, description
            break
    return voice.VoiceError(
        message, code=category, stage=stage, request_id=error.get('request_id') if isinstance(error, dict) else None
    )


def scope(settings):
    secret_hash = hashlib.sha256(feature_config.tts_secret(settings).encode()).hexdigest()
    return hashlib.sha256((settings.base_url + ':' + secret_hash).encode()).hexdigest()


def read_catalog():
    path = config.DATA_DIR / 'cloud-voices.json'
    if not path.exists():
        return []
    result = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result, list):
        raise voice.VoiceError('本地音色记录无法读取，请保留文件并检查数据目录。', 503)
    return result


def write_catalog(records):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = config.DATA_DIR / 'cloud-voices.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def remember(record):
    with LOCK:
        records = read_catalog()
        records = [x for x in records if (x['scope'], x['fingerprint']) != (record['scope'], record['fingerprint'])]
        write_catalog([*records, record])


def settings_now():
    from .tts_providers import aliyun_model_supported

    settings = feature_config.load().tts
    if settings.provider != 'aliyun' or not feature_config.tts_secret(settings):
        raise voice.VoiceError('请先选择百炼并保存 API Key。', 409)
    if not aliyun_model_supported(settings.model):
        raise voice.VoiceError('请选择支持声音复刻的 Qwen 实时模型。', 422)
    return settings


async def request(settings, fields):
    from .tts_providers import AUDIO_MODELS

    modern = settings.model in AUDIO_MODELS
    if modern:
        fields = {
            **fields,
            'action': {'list': 'list_voice', 'delete': 'delete_voice'}.get(fields['action'], fields['action']),
        }
        if 'voice' in fields:
            fields['voice_id'] = fields.pop('voice')
    raw, _ = await voice.upstream(
        settings,
        feature_config.tts_secret(settings),
        'POST',
        '/api/v1/services/audio/tts/customization',
        {'model': 'voice-enrollment' if modern else 'qwen-voice-enrollment', 'input': fields},
        maximum=2_000_000,
    )
    try:
        result = json.loads(raw)
        if result.get('code'):
            raise provider_error(result, 'voice_management')
        output = result['output']
        if not isinstance(output, dict):
            raise ValueError()
        return output
    except (ValueError, KeyError, TypeError):
        raise voice.VoiceError('百炼音色接口响应无效，请稍后刷新列表。', code='invalid_response') from None


async def list_voices():
    from .tts_providers import AUDIO_MODELS

    settings = settings_now()
    modern = settings.model in AUDIO_MODELS
    found = []
    for page in range(10):
        output = await request(settings, {'action': 'list', 'page_size': 100, 'page_index': page})
        items = output.get('voice_list')
        if not isinstance(items, list):
            raise voice.VoiceError('百炼音色列表结构不完整。', code='invalid_response')
        for item in items:
            voice_id = item.get('voice_id' if modern else 'voice') if isinstance(item, dict) else None
            if not isinstance(voice_id, str):
                raise voice.VoiceError('百炼音色记录无效。', code='invalid_response')
            matches = (
                voice_id.startswith(settings.model + '-') if modern else item.get('target_model') == settings.model
            )
            if matches:
                found.append(
                    {
                        'voice': voice_id,
                        'model': settings.model,
                        'created_at': item.get('gmt_create', ''),
                        'status': item.get('status', 'UNKNOWN') if modern else 'OK',
                    }
                )
        if len(items) < 100:
            break
    with LOCK:
        records = read_catalog()
        related = [x for x in records if x['scope'] == scope(settings) and x['model'] == settings.model]
        changed = False
        for item in found:
            local = next((x for x in related if x.get('voice') == item['voice']), None)
            if not local:
                local = next(
                    (x for x in related if x.get('state') == 'pending' and x['preferred_name'] in item['voice']), None
                )
                if local:
                    local.update(voice=item['voice'], state='ready')
                    changed = True
            item['name'] = local['name'] if local else item['voice']
        if changed:
            write_catalog(records)
    return {'voices': found, 'model': settings.model, 'selected': settings.voice}


def select(settings, voice_id):
    with feature_config.LOCK:
        current = settings_now()
        if scope(current) != scope(settings) or current.model != settings.model:
            raise voice.VoiceError('创建期间语音配置已改变，音色已保留，请刷新列表后重新选择。', 409)
        return feature_config.public(feature_config.update({'tts': {'voice': voice_id}}))


def uploaded_reference(encoded, audio_format):
    if audio_format not in ('mp3', 'wav'):
        raise voice.VoiceError('请选择 MP3/WAV 音频。', 422)
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise voice.VoiceError('上传音频编码无效。', 422) from None
    if not 0 < len(data) <= voice.MAX_REFERENCE_BYTES:
        raise voice.VoiceError('参考音频不得超过 6 MB。', 422)
    voice.validate_audio(data, audio_format)
    mime = 'audio/mpeg' if audio_format == 'mp3' else 'audio/wav'
    return {'sha256': hashlib.sha256(data).hexdigest()}, f'data:{mime};base64,' + encoded


async def create(name, encoded=None, audio_format='mp3'):
    from .tts_providers import AUDIO_MODELS, check_model, register_aliyun

    if not isinstance(name, str) or not name.strip() or len(name) > 60:
        raise voice.VoiceError('请填写 1–60 字的音色名称。', 422)
    async with MUTATIONS:
        settings = settings_now()
        if not settings.external_reference_enabled:
            raise voice.VoiceError('请先允许创建云端克隆音色并保存配置。', 409)
        reference = (
            uploaded_reference(encoded, audio_format)
            if encoded
            else await asyncio.to_thread(voice.cached_reference, settings.reference_path)
        )
        digest = reference[0]['sha256']
        fingerprint = hashlib.sha256((digest + settings.model).encode()).hexdigest()
        with LOCK:
            old = next(
                (x for x in read_catalog() if x['scope'] == scope(settings) and x['fingerprint'] == fingerprint), None
            )
        if old and old['state'] == 'pending':
            raise voice.VoiceError(
                '上次创建结果尚未确认。请先刷新云端音色列表，不要重复创建。', 409, code='creation_pending'
            )
        if old and old.get('voice'):
            # Check remote existence before reusing a cached ID.
            remote = await list_voices()
            existing = next((x for x in remote['voices'] if x['voice'] == old['voice']), None)
            if existing:
                if existing.get('status', 'OK') != 'OK':
                    raise voice.VoiceError(
                        '音色已存在但尚未就绪，请刷新查看审核状态，不要重复创建。', 409, code='voice_not_ready'
                    )
                return {
                    'voice': old['voice'],
                    'model': old['model'],
                    'features': select(settings, old['voice']),
                    'reused': True,
                }
        record = {
            'scope': scope(settings),
            'fingerprint': fingerprint,
            'name': name,
            'model': settings.model,
            'preferred_name': 'sg' + fingerprint[:8] if settings.model in AUDIO_MODELS else 'sg_' + fingerprint[:12],
            'state': 'pending',
            'voice': '',
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        # Persist before submission. A timeout/disconnect leaves a recoverable journal entry.
        await check_model(settings.model_copy(update={'voice': ''}))
        await asyncio.to_thread(remember, record)
        try:
            result = await register_aliyun(settings, record['preferred_name'], reference)
        except voice.VoiceError as error:
            if error.stage == 'upload':
                # No enrollment request has been sent; retrying cannot create a duplicate.
                with LOCK:
                    write_catalog(
                        [
                            x
                            for x in read_catalog()
                            if not (x['scope'] == record['scope'] and x['fingerprint'] == fingerprint)
                        ]
                    )
            elif error.retry_safe:
                record.update(state='failed', error_code=error.code)
                await asyncio.to_thread(remember, record)
            raise
        record.update(voice=result['voice'], state='ready', fallback_mode=result.get('fallback_mode', False))
        try:
            await asyncio.to_thread(remember, record)
            features = select(settings, result['voice'])
        except (OSError, RuntimeError):
            raise voice.VoiceError(
                f'云端音色已创建：{result["voice"]}。本地保存失败，请复制 ID 并刷新列表恢复。', 503
            ) from None
        return {
            'voice': result['voice'],
            'model': settings.model,
            'features': features,
            'fallback_mode': result.get('fallback_mode', False),
            'reused': False,
        }


async def choose(voice_id):
    async with MUTATIONS:
        settings = settings_now()
        available = await list_voices()
        if not any(x['voice'] == voice_id and x.get('status', 'OK') == 'OK' for x in available['voices']):
            raise voice.VoiceError('此音色不存在、模型不匹配或尚未审核通过，请刷新云端列表。', 409)
        return select(settings, voice_id)


async def delete(voice_id):
    async with MUTATIONS:
        settings = settings_now()
        available = await list_voices()
        if not any(x['voice'] == voice_id for x in available['voices']):
            raise voice.VoiceError('云端音色不存在或不属于当前模型。', 404)
        await request(settings, {'action': 'delete', 'voice': voice_id})
        with LOCK:
            write_catalog(
                [x for x in read_catalog() if not (x['scope'] == scope(settings) and x.get('voice') == voice_id)]
            )
        current = settings_now()
        if scope(current) == scope(settings) and current.voice == voice_id:
            return select(settings, '')
        return feature_config.public(feature_config.load())
