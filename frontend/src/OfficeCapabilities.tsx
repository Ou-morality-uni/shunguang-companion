import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { request } from './api';

type Capabilities = {
  office: { ready: boolean; version: string; message: string; install_url: string };
};

export function OfficeCapabilities() {
  const [value, setValue] = useState<Capabilities | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function check(signal?: AbortSignal) {
    setBusy(true);
    setError('');
    try {
      const result = await request<Capabilities>('/work/capabilities', { signal });
      if (!result?.office || typeof result.office.ready !== 'boolean')
        throw new Error('文件能力信息暂不可用，请更新并重启后端服务。');
      if (!signal?.aborted) setValue(result);
    } catch (failure) {
      if (!signal?.aborted) setError((failure as Error).message);
    } finally {
      if (!signal?.aborted) setBusy(false);
    }
  }
  useEffect(() => {
    const abort = new AbortController();
    void check(abort.signal);
    return () => abort.abort();
  }, []);
  return (
    <section className="reference-panel" aria-label="办公文件能力">
      <h3>办公文件能力</h3>
      <p role="status">{error || value?.office.message || '正在检测文件处理环境…'}</p>
      {value?.office.ready && <p className="space-note">{value.office.version}</p>}
      {!value?.office.ready && value && (
        <p>
          <a
            href="https://www.libreoffice.org/download/download-libreoffice/"
            target="_blank"
            rel="noopener noreferrer"
          >
            官方安装说明
          </a>{' '}
          安装完成后重新检测，无需修改模型配置。
        </p>
      )}
      <Button type="button" variant="outline" disabled={busy} aria-busy={busy} onClick={() => void check()}>
        {busy ? '检测中…' : '重新检测'}
      </Button>
    </section>
  );
}
