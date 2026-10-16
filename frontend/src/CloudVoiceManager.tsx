import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { request, type Features, type CloudVoice } from './api';

type Voice = CloudVoice;
type Props = { dirty: boolean; features: Features; onSaved: (features: Features) => void };

export function CloudVoiceManager({ dirty, features, onSaved }: Props) {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [name, setName] = useState('叶瞬光');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [deleting, setDeleting] = useState<Voice | null>(null);
  const [loaded, setLoaded] = useState(false);
  const available = !dirty && features.tts.provider === 'aliyun' && features.tts.has_api_key;
  const legacy = features.tts.model.startsWith('qwen3-tts-vc-realtime-');

  async function refresh() {
    const result = await request<{ voices: Voice[] }>('/tts/voices');
    setVoices(result.voices);
    setLoaded(true);
  }
  async function run(action: () => Promise<void>) {
    if (busy || !available) return;
    setBusy(true);
    setNotice('正在处理…');
    try {
      await action();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function create() {
    let audio_base64: string | undefined;
    if (file) {
      if (!file.name.toLowerCase().endsWith('.mp3') || file.size > 6_000_000)
        throw new Error('请选择不超过 6 MB 的 MP3。');
      audio_base64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(',')[1]);
        reader.onerror = () => reject(new Error('无法读取 MP3。'));
        reader.readAsDataURL(file);
      });
    }
    const result = await request<{
      voice: string;
      features: Features;
      fallback_mode?: boolean;
      reused?: boolean;
    }>('/tts/register', { method: 'POST', body: JSON.stringify({ name, audio_base64, format: 'mp3' }) });
    onSaved(result.features);
    setFile(null);
    setNotice(
      `${result.reused ? '已复用' : '已创建'}并保存音色：${result.voice}。${result.fallback_mode ? '厂商提示降级复刻，请先试听效果。' : '后续对话直接使用该 ID，无需原 MP3。'}`,
    );
    // Successful creation is already saved; a failed refresh must not imply creation failed.
    try {
      await refresh();
    } catch {
      setNotice(`音色 ${result.voice} 已创建并保存，列表刷新失败，可稍后重试。`);
    }
  }
  return (
    <div className="reference-panel" aria-label="百炼云端音色管理">
      <h3>百炼云端音色</h3>
      <p className="space-note">
        首次提交 MP3 创建音色，之后按音色 ID 合成。创建与合成分别计费；不会把 MP3
        归档到本机参考目录。Qwen-Audio-TTS 创建时使用百炼私有临时存储，样本在 48 小时后清理；音色 ID
        独立保留。
      </p>
      <label className="field">
        音色名称
        <Input
          aria-label="新音色名称"
          value={name}
          maxLength={60}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label className="field">
        临时选择 MP3（可选）
        <input
          type="file"
          accept=".mp3,audio/mpeg"
          disabled={busy}
          onChange={(event) => {
            setFile(event.target.files?.[0] || null);
            event.target.value = '';
          }}
        />
      </label>
      <p>{file ? `待创建：${file.name}` : '未选择文件时，使用下方已保存的参考 MP3 路径。'}</p>
      {file && (
        <Button type="button" variant="outline" disabled={busy} onClick={() => setFile(null)}>
          清除临时文件
        </Button>
      )}
      <Button
        type="button"
        variant="outline"
        disabled={busy || !available}
        onClick={() =>
          void run(async () => {
            const result = await request<{ ok: boolean; message?: string; stage?: string }>('/tts/check', {
              method: 'POST',
            });
            setNotice(
              result.message ||
                (result.ok ? '连接已建立，模型与音色仍需短句试听验证。' : '百炼连接检查失败。'),
            );
          })
        }
      >
        检查百炼连接
      </Button>
      <div className="inline-actions">
        <Button
          type="button"
          disabled={busy || !available || legacy || !features.tts.external_reference_enabled || !name.trim()}
          onClick={() => void run(create)}
        >
          创建并保存云端音色
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={busy || !available}
          onClick={() =>
            void run(async () => {
              await refresh();
              setNotice('云端音色列表已刷新，仅显示当前账号与绑定模型。');
            })
          }
        >
          刷新云端列表
        </Button>
      </div>
      {dirty && <p role="status">请先保存厂商、密钥、模型和外部处理许可，再管理云端音色。</p>}
      {legacy && (
        <p role="status">
          当前为旧 Qwen-TTS 配置。新建音色请先选择 Qwen-Audio-TTS 模型并保存；旧音色不能跨模型使用。
        </p>
      )}
      {loaded && voices.length === 0 && <p>当前模型下没有云端音色。</p>}
      {voices.map((item) => (
        <article className="source-card" key={item.voice}>
          <strong>
            {item.name}
            {features.tts.voice === item.voice ? ' · 当前使用' : ''}
          </strong>
          <p style={{ overflowWrap: 'anywhere' }}>{item.voice}</p>
          {item.status && item.status !== 'OK' && (
            <p>
              云端状态：
              {item.status === 'DEPLOYING'
                ? '审核处理中，请稍后刷新'
                : item.status === 'UNDEPLOYED'
                  ? '未通过审核，无法合成'
                  : item.status}
            </p>
          )}
          <small>
            {item.model} · {item.created_at}
          </small>
          <div className="inline-actions">
            <Button
              type="button"
              variant="outline"
              disabled={busy || !available || (!!item.status && item.status !== 'OK')}
              onClick={() =>
                void run(async () => {
                  const next = await request<Features>('/tts/voices/select', {
                    method: 'POST',
                    body: JSON.stringify({ voice: item.voice }),
                  });
                  onSaved(next);
                  setNotice('音色已选择并保存，可用下方测试按钮试听。');
                })
              }
            >
              选择并保存
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                void navigator.clipboard
                  .writeText(item.voice)
                  .then(() => setNotice('音色 ID 已复制。'))
                  .catch(() => setNotice('复制失败，请手动选择 ID 复制。'))
              }
            >
              复制 ID
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy || !available}
              onClick={() => setDeleting(item)}
            >
              删除
            </Button>
          </div>
        </article>
      ))}
      {deleting && (
        <div role="alert" className="settings-notice">
          <p>
            确认删除云端音色“{deleting.name}”（{deleting.voice}）？删除后不能继续用该 ID
            合成；当前选中的音色也会清空。
          </p>
          <Button
            type="button"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                const next = await request<Features>('/tts/voices/delete', {
                  method: 'POST',
                  body: JSON.stringify({ voice: deleting.voice }),
                });
                onSaved(next);
                setDeleting(null);
                await refresh();
                setNotice('云端音色已删除。');
              })
            }
          >
            确认删除该音色
          </Button>
          <Button type="button" variant="outline" disabled={busy} onClick={() => setDeleting(null)}>
            取消
          </Button>
        </div>
      )}
      {notice && (
        <p className="settings-notice" role="status">
          {notice}
        </p>
      )}
    </div>
  );
}
