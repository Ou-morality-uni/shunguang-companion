import asyncio
import base64
import hashlib
import ipaddress
import json
import socket
from urllib.parse import urlsplit

import httpx

from .. import config, document_models, stickers
from ..document_readers import image_bytes

MAX_BYTES = 8 * 1024 * 1024


def sticker_segment(value):
    if not isinstance(value, dict):
        return None
    item = next((item for item in stickers.load_catalog()['items'] if item['id'] == value.get('id')), None)
    if not item:
        return None
    directory = (config.ROOT / 'source/resources/character/stickers').resolve()
    try:
        path = (directory / item['file']).resolve()
        if not path.is_relative_to(directory) or path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
        if not data or len(data) > MAX_BYTES:
            return None
        return {
            'type': 'image',
            'data': {
                'file': 'base64://' + base64.b64encode(data).decode('ascii'),
                'sub_type': 1,
                'summary': '[叶瞬光表情]',
            },
        }
    except OSError:
        return None


async def download(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ''
    if (
        parsed.scheme != 'https'
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not (host.endswith('.qpic.cn') or host in ('multimedia.nt.qq.com', 'multimedia.nt.qq.com.cn'))
    ):
        raise ValueError('只允许 QQ 图片服务器的 HTTPS 地址')
    addresses = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('图片地址不得指向本机或内网')
    # Pin the checked address, preserving TLS verification against the original QQ hostname.
    target = httpx.URL(url).copy_with(host=addresses[0][4][0])
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
        async with client.stream('GET', target, headers={'Host': host}, extensions={'sni_hostname': host}) as response:
            response.raise_for_status()
            if not response.headers.get('content-type', '').lower().startswith('image/'):
                raise ValueError('返回内容不是图片')
            result = bytearray()
            async for part in response.aiter_bytes():
                result.extend(part)
                if len(result) > MAX_BYTES:
                    raise ValueError('图片超过 8 MB')
    return await asyncio.to_thread(image_bytes, bytes(result))


async def fetch_images(repo, event):
    if 'kind' in event:
        current = repo.policy(event['kind'], event['target'])
        if not current.collect or not current.images:
            return
    segments = json.loads(event['segments'])
    for index, item in enumerate([segment for segment in segments if segment['type'] == 'image'][:4]):
        key = hashlib.sha256(f'{event["id"]}:{index}'.encode()).hexdigest()
        with repo.connect() as db:
            existing = db.execute('SELECT data,attempts FROM images WHERE id=?', (key,)).fetchone()
            if existing:
                if existing['data'] or existing['attempts'] >= 2:
                    continue
                reserved = db.execute(
                    'UPDATE images SET attempts=attempts+1 WHERE id=? AND data IS NULL AND attempts<2', (key,)
                )
                if not reserved.rowcount:
                    continue
            else:
                reserved = db.execute(
                    'INSERT OR IGNORE INTO images(id,event,error,attempts) VALUES (?,?,?,1)',
                    (key, event['id'], '图片获取中'),
                )
                if not reserved.rowcount:
                    continue
        data, error = None, ''
        try:
            data = await download(item['data'].get('url', ''))
        except ValueError:
            error = '图片获取失败：链接失效、来源不允许、格式或大小不支持'
        except Exception:
            error = '图片获取失败：网络、下载服务或链接不可用'
        with repo.connect() as db:
            db.execute('UPDATE images SET data=?,error=? WHERE id=? AND data IS NULL', (data, error, key))


async def describe(repo, event, policy):
    if not any(item['type'] == 'image' for item in json.loads(event['segments'])):
        return ''
    if not policy.images:
        return '\n[图片未识别：此场景未启用图片]'
    value = document_models.selected(policy.vision_profile, policy.vision_signature)
    if value is None:
        return '\n[图片未识别：视觉模型或授权已变化，请在面板重新选择并启用]'
    with repo.connect() as db:
        images = [dict(row) for row in db.execute('SELECT * FROM images WHERE event=? ORDER BY id', (event['id'],))]
    answers = []
    for item in images:
        if not item['data']:
            answers.append('[图片未识别：' + item['error'] + ']')
            continue

        def check():
            if 'kind' in event:
                current = repo.policy(event['kind'], event['target'])
                if (
                    not current.images
                    or not current.collect
                    or current.vision_signature != policy.vision_signature
                    or current.vision_profile != policy.vision_profile
                ):
                    raise ValueError('图片授权已撤销')
            if document_models.selected(policy.vision_profile, policy.vision_signature) is None:
                raise ValueError('视觉配置已变化')

        try:
            check()
            if item['signature'] != policy.vision_signature or not item['description']:
                answer = await document_models.recognize(
                    value, {'data': item['data'], 'location': 'QQ 图片（动态图只读取首帧）'}, check, lambda: None
                )
                check()
                with repo.connect() as db:
                    db.execute(
                        'UPDATE images SET signature=?,description=?,error=? WHERE id=?',
                        (policy.vision_signature, answer, '', item['id']),
                    )
            else:
                answer = item['description']
            answers.append('[图片读取结果，动态图仅首帧：' + answer + ']')
        except Exception as exc:
            error = (
                '图片识别超时：可在模型设置调高超时，保存后选择视觉模型并重新授权'
                if isinstance(exc, (TimeoutError, httpx.TimeoutException))
                else '图片识别失败：模型不可用或授权变化'
            )
            with repo.connect() as db:
                db.execute('UPDATE images SET error=? WHERE id=?', (error, item['id']))
            answers.append('[' + error + ']')
    total = sum(item['type'] == 'image' for item in json.loads(event['segments']))
    if total > len(images):
        answers.append(f'[另有 {total - len(images)} 张图片未识别，单条消息最多处理 4 张]')
    return '\n' + '\n'.join(answers)
