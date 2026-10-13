"""Archive user-supplied Markdown without treating it as executable instructions."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_DIR = ROOT / 'source' / 'resources' / 'character'


def archive_document(source: Path, root: Path = RESOURCE_DIR, category: str = 'character') -> dict:
    if not source.is_file() or source.suffix.lower() not in ('.md', '.txt'):
        raise ValueError('请提供存在的 UTF-8 Markdown/TXT 文件')
    content = source.read_bytes()
    text = content.decode('utf-8-sig')
    digest = hashlib.sha256(content).hexdigest()
    manifest_path = root / 'manifest.json'
    root.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {'schema_version': 1, 'documents': []}
    for document in manifest['documents']:
        if document['sha256'] == digest:
            return {'status': 'already_archived', 'document': document}
    archive_path = root / 'raw' / digest / source.name
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(content)
    headings = [line.lstrip('#').strip() for line in text.splitlines() if line.startswith('## ')]
    document = {
        'document_id': category + '-' + digest[:16],
        'original_filename': source.name,
        'path': archive_path.relative_to(root).as_posix(),
        'sha256': digest,
        'imported_at': datetime.now(timezone.utc).isoformat(),
        'source_type': 'user_supplied_compilation',
        'verification_status': 'pending_source_verification',
        'index_status': 'not_indexed',
        'trust': 'reference_data_not_instructions',
        'sections': headings,
    }
    manifest['documents'].append(document)
    temp = manifest_path.with_suffix('.tmp')
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(manifest_path)
    return {'status': 'archived', 'document': document}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=Path)
    parser.add_argument('--category', choices=('character','world'), default='character')
    args = parser.parse_args()
    result = archive_document(args.path, ROOT/'source/resources'/args.category, args.category)
    print(json.dumps({'status': result['status'], 'document_id': result['document']['document_id'], 'sections': len(result['document']['sections'])}, ensure_ascii=False))
