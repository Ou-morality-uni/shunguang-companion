import { useState } from 'react';
import { Check, LoaderCircle } from 'lucide-react';
import { request, type Features, type ModelSettings } from './api';
import { Button } from './components/ui/button';
import { Input } from './components/ui/input';
import { Switch } from './components/ui/switch';
import { GlideSelect } from './components/ui/glide-select';

export function ASRSettings({
  value,
  connections,
  onSaved,
}: {
  value?: Features['asr'];
  connections: Array<ModelSettings & { id: string }>;
  onSaved: (value: Features) => void;
}) {
  const [draft, setDraft] = useState(
    value || {
      enabled: false,
      base_url: 'https://api.openai.com/v1',
      model: 'gpt-transcribe',
      profile_id: '',
      timeout: 60,
      configured: false,
      has_api_key: false,
    },
  );
  const [key, setKey] = useState(''),
    [clear, setClear] = useState(false),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState('');
  const compatible = connections.filter((item) => {
    try {
      return new URL(item.base_url).origin === new URL(draft.base_url).origin && item.has_api_key;
    } catch {
      return false;
    }
  });
  async function save() {
    if (busy) return;
    setBusy(true);
    setNotice('');
    try {
      const { enabled, base_url, model, profile_id, timeout } = draft;
      const result = await request<Features>('/features', {
        method: 'PATCH',
        body: JSON.stringify({
          asr: {
            enabled,
            base_url,
            model,
            profile_id,
            timeout,
            api_key: key || undefined,
            clear_api_key: clear,
          },
        }),
      });
      if (result.asr) setDraft(result.asr);
      setKey('');
      setClear(false);
      onSaved(result);
      setNotice(
        result.asr?.configured
          ? '识别设置已保存。点击输入区麦克风开始，识别后检查草稿再发送。'
          : '设置已保存；仍需配置有效识别模型与密钥。',
      );
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      className="asr-settings"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <h2>语音输入</h2>
      <div className="setting-toggle">
        <div>
          <strong>在线语音识别</strong>
          <p>录音结束后发往所选识别服务，转成草稿，检查后由你发送。</p>
        </div>
        <Switch
          aria-label="在线语音识别"
          checked={draft.enabled}
          onCheckedChange={(enabled) => setDraft({ ...draft, enabled })}
          disabled={busy}
        />
      </div>
      <fieldset disabled={busy}>
        <label className="field">
          识别 API 地址
          <Input
            aria-label="识别 API 地址"
            value={draft.base_url}
            maxLength={500}
            required
            onChange={(event) => {
              setDraft({ ...draft, base_url: event.target.value, has_api_key: false, profile_id: '' });
              setKey('');
              setClear(false);
            }}
          />
          <span className="field-hint">HTTPS 的 OpenAI 兼容接口根地址；实际请求 /audio/transcriptions。</span>
        </label>
        <label className="field">
          识别模型
          <Input
            aria-label="识别模型"
            value={draft.model}
            maxLength={150}
            required
            onChange={(event) => setDraft({ ...draft, model: event.target.value })}
          />
        </label>
        <label className="field">
          识别密钥来源
          <GlideSelect
            label="识别密钥来源"
            value={draft.profile_id || 'independent'}
            options={[
              { value: 'independent', label: '独立识别密钥' },
              ...compatible.map((item) => ({
                value: item.id,
                label: `${item.provider} · ${item.model}`,
                group: '同源已保存连接',
              })),
              ...(draft.profile_id && !compatible.some((item) => item.id === draft.profile_id)
                ? [{ value: draft.profile_id, label: '已选连接（暂不可用）', disabled: true }]
                : []),
            ]}
            onValueChange={(value) =>
              setDraft({ ...draft, profile_id: value === 'independent' ? '' : value })
            }
            disabled={busy}
          />
        </label>
        {!draft.profile_id && (
          <label className="field">
            识别 API 密钥
            <Input
              aria-label="识别 API 密钥"
              type="password"
              autoComplete="off"
              maxLength={2048}
              value={key}
              disabled={clear}
              placeholder={draft.has_api_key ? '已加密保存；留空保留，填写替换' : '填写识别服务密钥'}
              onChange={(event) => setKey(event.target.value)}
            />
          </label>
        )}
        {draft.has_api_key && (
          <button
            type="button"
            className="clear-key"
            onClick={() => {
              setClear(!clear);
              setKey('');
            }}
          >
            {clear ? '取消移除识别密钥' : '明确移除独立识别密钥'}
          </button>
        )}
        <p className="space-note">
          每段最多 2 分钟、10
          MiB；录音不保存为附件。聊天模型能否接收音频，不能代替识别接口支持；复用密钥只允许所选连接的同源接口。
        </p>
        <div className="modal-actions">
          <Button type="submit" disabled={busy} aria-busy={busy}>
            {busy ? <LoaderCircle size={15} className="spin" /> : <Check size={15} />}保存识别配置
          </Button>
        </div>
      </fieldset>
      {notice && (
        <p role="status" className="space-note">
          {notice}
        </p>
      )}
    </form>
  );
}
