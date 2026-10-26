import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { request, type UpdateCheck } from './api';

const repository = 'https://github.com/Ou-morality-uni/shunguang-companion';

export function UpdateSettings({
  currentVersion,
  onRefreshVersion,
}: {
  currentVersion: string | null;
  onRefreshVersion: () => Promise<void>;
}) {
  const [result, setResult] = useState<UpdateCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  async function check() {
    if (active.current) return;
    const abort = new AbortController();
    active.current = abort;
    setBusy(true);
    setError('');
    setResult(null);
    try {
      const value = await request<UpdateCheck>('/updates/check', { method: 'POST', signal: abort.signal });
      if (!abort.signal.aborted) setResult(value);
    } catch (failure) {
      if (!abort.signal.aborted) setError((failure as Error).message);
    } finally {
      if (!abort.signal.aborted) {
        active.current = null;
        setBusy(false);
      }
    }
  }

  return (
    <section className="reference-panel update-settings" aria-label="关于与更新">
      <h3>关于与更新</h3>
      <p>当前版本：{currentVersion ? `v${currentVersion}` : '版本未知'}</p>
      {!currentVersion && (
        <Button
          type="button"
          variant="outline"
          onClick={() => void onRefreshVersion().catch((failure: Error) => setError(failure.message))}
        >
          重新读取版本
        </Button>
      )}
      <p className="space-note">仅点击按钮时联网检查正式版本。同版本的代码补充不会提示新版本。</p>
      <Button type="button" variant="outline" disabled={busy} aria-busy={busy} onClick={() => void check()}>
        {busy ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}
        {busy ? '正在检查更新…' : '检查更新'}
      </Button>
      <div aria-live="polite" aria-atomic="true">
        {busy && <p role="status">正在检查更新，请稍候。</p>}
        {error && <p role="alert">{error}</p>}
        {result && (
          <div>
            <p role="status">
              {result.status === 'available'
                ? `发现新版本 v${result.latest_version}`
                : result.status === 'ahead'
                  ? `本机版本高于公开版本 v${result.latest_version}，无需降级。`
                  : `当前已是最新版本 v${result.latest_version}`}
            </p>
            <p className="space-note">
              检查时间：{new Date(result.checked_at).toLocaleString()}
              {result.cached && '（最近一分钟的缓存结果）'}
            </p>
            {result.status === 'available' && (
              <>
                <p>发布日期：{result.published_at}</p>
                <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{result.summary}</p>
                <a href={result.release_notes_url} target="_blank" rel="noopener noreferrer">
                  查看更新说明
                </a>
              </>
            )}
          </div>
        )}
      </div>
      <details>
        <summary>更新方法</summary>
        <p>在运行后端的电脑上操作；手机通过局域网访问时，也请回到该电脑更新。</p>
        <ol>
          <li>在后端窗口按 Ctrl+C 停止服务。关闭网页不会停止后端。</li>
          <li>
            在项目根目录执行 <code>git pull --ff-only</code>，或在 GitHub Desktop 点击 Fetch origin，再点击
            Pull origin。
          </li>
          <li>运行 Install.bat，等待出现 Installation success，再运行 Start_up.bat，启动后刷新网页。</li>
        </ol>
        <p>更新前备份并保留自己的 data/。源码存在修改冲突时先处理，不要强制覆盖。</p>
        <p>ZIP 用户请按 README 下载新代码并保留个人数据。检查按钮不会下载安装或重启服务。</p>
        <a
          href={`${repository}/blob/main/README.md#更新与常见问题`}
          target="_blank"
          rel="noopener noreferrer"
        >
          完整更新步骤（含 ZIP）
        </a>
      </details>
      <p>
        <a href={repository} target="_blank" rel="noopener noreferrer">
          项目 GitHub 仓库
        </a>
      </p>
    </section>
  );
}
