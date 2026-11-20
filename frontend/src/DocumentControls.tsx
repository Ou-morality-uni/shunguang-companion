import { GlideSelect } from './components/ui/glide-select';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { request } from './api';

type VisionProfile = {
  id: string;
  model: string;
  base_url: string;
  service: string;
  signature: string;
  external: boolean;
};

export function VisionApproval({
  taskId,
  info,
  onChanged,
  onModelSettings,
}: {
  taskId: string;
  info: Record<string, unknown>;
  onChanged: () => Promise<void>;
  onModelSettings?: () => void;
}) {
  const [profiles, setProfiles] = useState<VisionProfile[]>([]),
    [chosen, setChosen] = useState('');
  const [busy, setBusy] = useState(false),
    [notice, setNotice] = useState('');
  const selected = profiles.find((item) => item.id === chosen);
  async function load() {
    try {
      setProfiles(await request<VisionProfile[]>('/work/vision/profiles'));
    } catch (error) {
      setNotice((error as Error).message);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  async function decide(approved: boolean) {
    if (approved && !selected) return;
    setBusy(true);
    setNotice('');
    try {
      await request(`/work/tasks/${taskId}/vision`, {
        method: 'POST',
        body: JSON.stringify({
          approved,
          ...(approved && selected ? { profile_id: selected.id, signature: selected.signature } : {}),
        }),
      });
      await onChanged();
    } catch (error) {
      setNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="work-approval" role="group" aria-label="替代图像识别授权">
      <p>当前模型无法直接完成这部分图像识别。你可以选择另一项已配置的视觉能力，继续原任务。</p>
      <p>
        文件：{String(info.file)}；位置：{Array.isArray(info.locations) ? info.locations.join('、') : ''}
      </p>
      <p>
        {String(info.reason)} {String(info.message)}
      </p>
      {typeof info.scope === 'string' && <p>{info.scope}</p>}
      <label className="field">
        本任务的替代视觉服务
        <GlideSelect
          label="本任务的替代视觉服务"
          placeholder="请选择已确认支持视觉的模型"
          value={chosen}
          onValueChange={setChosen}
          options={profiles.map((profile) => ({
            value: profile.id,
            label: `${profile.service} / ${profile.model}`,
          }))}
        />
      </label>
      {selected && (
        <p>
          图像将发送到：{selected.base_url}；模型：{selected.model}。
          {selected.external
            ? '这是外部模型服务，会将图像发送到本机之外。'
            : '这是本机模型服务，不需要将图像发送到外部服务。'}
          {info.scope ? '仅本任务这份文件中授权范围内的图像，' : '仅本任务所列图像，'}可能按服务规则计费。
        </p>
      )}
      {!profiles.length && (
        <p>
          目前没有可用的替代视觉模型。请先在模型连接中保存并确认视觉能力；授权本身不会安装或创造识别能力。
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      <div className="work-actions">
        <Button disabled={busy || !selected} onClick={() => void decide(true)}>
          同意本任务使用所选服务
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => void decide(false)}>
          拒绝并保留已读内容
        </Button>
        <Button variant="ghost" disabled={busy} onClick={() => void load()}>
          刷新可用服务
        </Button>
        {onModelSettings && (
          <Button variant="ghost" onClick={onModelSettings}>
            配置视觉模型
          </Button>
        )}
      </div>
    </div>
  );
}
