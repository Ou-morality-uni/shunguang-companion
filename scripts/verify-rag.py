"""Actual GPU/embedding/Qdrant evaluation. Run in .venv-rag; no provider API calls."""
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app import rag

output_dir = ROOT / 'artifacts/rag-evaluation'
output_dir.mkdir(parents=True, exist_ok=True)
resources = output_dir / ('resources-' + str(int(time.time())))
for category in ('character', 'world'):
    source = rag.RESOURCE_DIR / category
    for name in ('manifest.json', 'raw'):
        destination = resources / category / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if (source / name).is_dir():
            shutil.copytree(source / name, destination)
        else:
            shutil.copy2(source / name, destination)
shutil.copytree(rag.RESOURCE_DIR / 'verified', resources / 'verified')
index = rag.LocalIndex(output_dir / resources.name.replace('resources-', 'data-'), resource_directory=resources)
report = {'test_type': 'real_local_GPU_BGE_M3_and_Qdrant', 'provider_api_used': False, 'cases': []}
try:
    report['probe'] = index.probe()
    report['initial_build'] = index.rebuild()
    cases = [
        ('叶瞬光属于哪个阵营？', '云岿山', False),
        ('为什么叫你二师姐？', '二师姐', False),
        ('叶释渊与你是什么关系？', '哥哥', False),
        ('新艾利都和空洞是什么？', '空洞', False),
        ('青溟剑会给剑主带来什么代价？', '反噬', True),
        ('你的具体希人种属已经确定了吗？', '未有定论', False),
        ('叶瞬光的霜烬剑第七式叫什么？', '霜烬剑第七式', False),
    ]
    for query, expected, spoilers in cases:
        started = time.perf_counter()
        found = index.search(query, 4, allow_spoilers=spoilers)
        report['cases'].append({'query': query, 'allow_spoilers': spoilers,
                                'seconds': round(time.perf_counter() - started, 4),
                                'evidence_contains_expected': any(expected in item['text'] for item in found),
                                'expected_phrase': expected,
                                'sources': [{key: item.get(key) for key in ('id', 'title', 'text', 'score', 'source_url',
                                                                          'verification_status', 'sha256', 'spoiler', 'historical')}
                                            for item in found]})
    report['no_change_build'] = index.rebuild()
    raw = '# 实际增量验收\n\n## 资料标记\n索引增量验收口令是「暖霞映山川」，这是开发测试资料，不是游戏事实。'.encode('utf-8')
    digest = hashlib.sha256(raw).hexdigest()
    path = resources / 'character/raw' / digest / 'incremental-test.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    manifest_path = resources / 'character/manifest.json'
    manifest = rag.read_json(manifest_path, {})
    manifest['documents'].append({'document_id': 'rag-acceptance-' + digest[:16], 'original_filename': path.name,
                                 'path': path.relative_to(resources / 'character').as_posix(), 'sha256': digest,
                                 'imported_at': '2026-10-12T10:00:00Z', 'source_type': 'development_acceptance_fixture'})
    rag.write_json(manifest_path, manifest)
    report['incremental_build'] = index.rebuild()
    report['incremental_search'] = index.search('索引增量验收口令是什么？', 4)
    assert any('暖霞映山川' in item['text'] for item in report['incremental_search'])
    manifest['documents'].pop()
    rag.write_json(manifest_path, manifest)
    report['removed_build'] = index.rebuild()
    assert report['removed_build']['removed_documents'] == 1
    assert not any('暖霞映山川' in item['text'] for item in index.search('索引增量验收口令是什么？', 4))
    conflict = rag.LocalIndex(index.directory)
    try:
        conflict.open()
        report['single_owner_lock'] = False
    except rag.RagError:
        report['single_owner_lock'] = True
    index.close()
    index = rag.LocalIndex(index.directory, resource_directory=resources)
    restarted = index.search('叶瞬光属于哪个阵营？', 4)
    report['restart_search_verified'] = any('云岿山' in item['text'] for item in restarted)
    assert report['restart_search_verified']
    report['completed'] = True
finally:
    index.close()
    rag.write_json(output_dir / 'report.json', report)
print(json.dumps({key: value for key, value in report.items() if key not in ('cases', 'incremental_search')}, ensure_ascii=True, indent=2))
