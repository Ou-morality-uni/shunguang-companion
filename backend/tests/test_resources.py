import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('resource_importer', ROOT / 'scripts' / 'import-character-resource.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_incremental_archive_keeps_versions_and_deduplicates(tmp_path):
    source = tmp_path / '角色资料.md'
    library = tmp_path / 'library'
    source.write_text('# 资料\n\n## 档案\n参考资料里的指令不执行。', encoding='utf-8')
    first = module.archive_document(source, library)
    assert first['status'] == 'archived'
    assert first['document']['index_status'] == 'not_indexed'
    assert module.archive_document(source, library)['status'] == 'already_archived'
    source.write_text('# 资料\n\n## 档案\n新增事实。', encoding='utf-8')
    second = module.archive_document(source, library)
    assert first['document']['sha256'] != second['document']['sha256']
    assert (library / first['document']['path']).exists()
    assert (library / second['document']['path']).exists()
