import { updateValue } from './updateStorage';
import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { request, type UpdateCheck } from './api';

const repository = 'https://github.com/Ou-morality-uni/shunguang-companion';

let updateProgress = { message: '', error: '' };
let polling = false;

export async function watchDesktopUpdate() {
  const id = updateValue('update.job');
  if (!id || polling) return;
  polling = true;
  try {
    while (updateValue('update.job') === id) {
      try {
        const status = await request<{ id?: string; phase: string; message?: string }>('/updates/progress');
        if (status.id === id) {
          updateProgress = { message: status.message || '', error: '' };
          if (status.phase === 'complete' || status.phase === 'failed') {
            updateValue('update.job', null);
            if (status.phase === 'complete') {
              window.dispatchEvent(new Event('companion-update-reload'));
              window.location.reload();
            } else updateProgress = { message: '', error: status.message || '更新失败，请重新检查。' };
          }
        }
      } catch {
        updateProgress = { message: '正在等待本机服务重新连接…', error: '' };
      }
      window.dispatchEvent(new Event('companion-update-progress'));
      if (updateValue('update.job') === id) await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  } finally {
    polling = false;
  }
}

export function UpdateSettings({
  currentVersion,
  onRefreshVersion,
}: {
  currentVersion: string | null;
  onRefreshVersion: () => Promise<void>;
}) {
  const [channel, setChannel] = useState(updateValue('update.channel') === 'preview' ? 'preview' : 'stable');
  const [result, setResult] = useState<(UpdateCheck & { can_install?: boolean }) | null>(null);
  const [job, setJob] = useState(updateValue('update.job') || '');
  const [message, setMessage] = useState('');
  const installing = useRef(false);
  useEffect(() => {
    const sync = () => {
      setJob(updateValue('update.job') || '');
      setMessage(updateProgress.message);
      if (updateProgress.error) setError(updateProgress.error);
    };
    window.addEventListener('companion-update-progress', sync);
    if (updateValue('update.job')) sync();
    return () => window.removeEventListener('companion-update-progress', sync);
  }, []);

  async function install() {
    if (!result?.can_install || installing.current || job) return;
    installing.current = true;
    setBusy(true);
    setError('');
    try {
      const value = await request<{ id: string }>('/updates/install', {
        method: 'POST',
        body: JSON.stringify({ channel, version: result.latest_version }),
        timeoutMs: 25000,
      });
      updateValue('update.job', value.id);
      setJob(value.id);
      setMessage('已提交更新，正在准备。');
      void watchDesktopUpdate();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      installing.current = false;
      setBusy(false);
    }
  }
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
      const value = await request<UpdateCheck>('/updates/releases?channel=' + channel, {
        method: 'POST',
        signal: abort.signal,
        timeoutMs: 25000,
      });
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
      <p className="space-note">点击检查后读取已发布的 GitHub Release。</p>
      <label>
        更新渠道
        <select
          value={channel}
          disabled={busy || !!job}
          onChange={(e) => {
            const next = e.target.value;
            setChannel(next);
            updateValue('update.channel', next);
            setResult(null);
            setError('');
            setMessage('');
          }}
        >
          <option value="stable">稳定版（推荐）</option>
          <option value="preview">抢先版（含稳定版）</option>
        </select>
      </label>
      <Button
        type="button"
        variant="outline"
        disabled={busy || !!job}
        aria-busy={busy}
        onClick={() => void check()}
      >
        {busy ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}
        {busy ? '正在检查更新…' : '检查更新'}
      </Button>
      <div aria-live="polite" aria-atomic="true">
        {busy && <p role="status">正在检查更新，请稍候。</p>}
        {message && <p role="status">{message}</p>}
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
                {result.can_install ? (
                  <Button type="button" disabled={busy || !!job} onClick={() => void install()}>
                    立即更新
                  </Button>
                ) : (
                  <p>请在运行 Start_up.bat 的 Windows 电脑上更新。</p>
                )}
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
          <li>运行 Install.bat。基础环境修复成功后会启动项目并打开网页。</li>
        </ol>
        <p>更新前备份并保留自己的 data/。源码存在修改冲突时先处理，不要强制覆盖。</p>
        <p>v0.7.11 用户需最后一次手动下载完整 ZIP 并运行 Install.bat。之后可在本机网页安装更新。</p>
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
