import { useEffect, useState } from 'react';
import { RefreshCw, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { request, type Workspace } from './api';
import { useResourcePreview } from './PreviewContext';

type UploadRecord = { id: string; name: string; bytes: number; created_at: string };
export function WorkSpace({ onModelSettings: _settings }: { onModelSettings?: () => void }) {
  const [files, setFiles] = useState<UploadRecord[]>([]),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  const open = useResourcePreview();
  async function refresh(signal?: AbortSignal) {
    setBusy(true);
    try {
      const result = await request<UploadRecord[]>('/work/uploads', { signal });
      if (!signal?.aborted) {
        setFiles(Array.isArray(result) ? result : []);
        setError('');
      }
    } catch (failure) {
      if (!signal?.aborted) setError((failure as Error).message);
    } finally {
      if (!signal?.aborted) setBusy(false);
    }
  }
  useEffect(() => {
    const abort = new AbortController();
    void refresh(abort.signal);
    return () => abort.abort();
  }, []);
  return (
    <div className="space-page workbench upload-records">
      <div className="page-heading">
        <span className="eyebrow">YOUR DOCUMENTS</span>
        <h1>上传记录</h1>
        <p>从聊天上传的资料保存在本机；这里显示最近 200 份，可随时打开预览。</p>
      </div>
      <div className="work-actions">
        <Button variant="outline" disabled={busy} onClick={() => void refresh()}>
          <RefreshCw size={14} className={busy ? 'spin' : ''} />
          刷新
        </Button>
      </div>
      {error && <p role="status">{error}</p>}
      {!files.length && !busy && <p className="empty-state">还没有上传资料。在聊天中添加文件即可。</p>}
      <ul className="upload-record-list">
        {files.map((file) => (
          <li key={file.id}>
            <FileText size={19} />
            <div>
              <strong>{file.name}</strong>
              <small>
                {(file.bytes / 1024).toFixed(1)} KiB · {new Date(file.created_at).toLocaleDateString('zh-CN')}
              </small>
            </div>
            <Button
              variant="outline"
              aria-label={`预览 ${file.name}`}
              onClick={(event) =>
                open?.({ kind: 'attachment', id: file.id, title: file.name }, event.currentTarget)
              }
            >
              预览
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function FilePermissions() {
  const [folders, setFolders] = useState<Workspace[]>([]),
    [path, setPath] = useState(''),
    [notice, setNotice] = useState(''),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    const abort = new AbortController();
    void request<Workspace[]>('/work/workspaces', { signal: abort.signal })
      .then((result) => {
        if (!abort.signal.aborted) setFolders(Array.isArray(result) ? result : []);
      })
      .catch((error) => {
        if (!abort.signal.aborted) setNotice(error.message);
      });
    return () => abort.abort();
  }, []);
  async function grant() {
    setBusy(true);
    try {
      await request('/work/workspaces', { method: 'POST', body: JSON.stringify({ path }) });
      setFolders(await request<Workspace[]>('/work/workspaces'));
      setPath('');
      setNotice('工作文件夹已授权。');
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="reference-panel">
      <summary>本机文件夹授权</summary>
      <p className="space-note">
        授权后可在聊天中读取、整理或修改范围内的文件；删除和覆盖仍需确认，修改前保留恢复备份。
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void grant();
        }}
      >
        <label className="field">
          本机文件夹完整路径
          <Input value={path} onChange={(event) => setPath(event.target.value)} maxLength={1000} required />
        </label>
        <Button type="submit" disabled={busy || !path.trim()}>
          授权此文件夹
        </Button>
      </form>
      <ul className="work-folders">
        {folders
          .filter((folder) => folder.enabled)
          .map((folder) => (
            <li key={folder.id}>
              <span>{folder.path}</span>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  void request(`/work/workspaces/${folder.id}`, { method: 'DELETE' })
                    .then(() => {
                      setFolders((items) => items.filter((item) => item.id !== folder.id));
                      setNotice('已撤销授权，相关任务停止；原文件和备份保留。');
                    })
                    .catch((error) => setNotice(error.message))
                    .finally(() => setBusy(false));
                }}
              >
                撤销授权
              </Button>
            </li>
          ))}
      </ul>
      {notice && <p role="status">{notice}</p>}
    </details>
  );
}
