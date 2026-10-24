import { GlideSelect } from './components/ui/glide-select';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { request, type FileTaskInput, type Workspace } from './api';

type Step = FileTaskInput['steps'][number];
type VisionProfile = {
  id: string;
  model: string;
  base_url: string;
  service: string;
  signature: string;
  external: boolean;
};

export function UploadDocuments({
  onUploaded,
  onModelSettings,
}: {
  onUploaded: (workspace: Workspace, steps: Step[]) => void;
  onModelSettings?: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [notice, setNotice] = useState('');
  return (
    <section className="work-card glass" aria-label="上传阅读资料">
      <h3>把资料交给瞬光</h3>
      <p className="space-note">
        支持 PDF、docx、xlsx、pptx、代码和图片；每份最多 20 MiB，一次最多 10
        份。副本保存在本机附件区。提交阅读后，已确认支持视觉的当前模型会直接处理必要图像；替代服务另行授权。
      </p>
      <label className="field">
        选择上传文件
        <input
          type="file"
          multiple
          disabled={busy}
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            event.target.value = '';
            if (!files.length) return;
            if (files.length > 10 || files.some((file) => file.size > 20 * 1024 * 1024)) {
              setNotice('一次最多 10 份，每份最多 20 MiB。');
              return;
            }
            void (async () => {
              setBusy(true);
              setNotice('正在保存上传副本。');
              try {
                const steps: Step[] = [];
                let workspace: Workspace | null = null;
                for (const file of files) {
                  const result = await request<{ workspace: Workspace; path: string }>(
                    `/work/upload?name=${encodeURIComponent(file.name)}`,
                    {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/octet-stream' },
                      body: file,
                    },
                  );
                  workspace = result.workspace;
                  steps.push({ action: 'read_document', path: result.path, start: 1, limit: 20 });
                }
                if (workspace) onUploaded(workspace, steps);
                setNotice('副本已保存，阅读任务已填好。核对范围和阅读要求后，点击提交任务。');
              } catch (error) {
                setNotice((error as Error).message);
              } finally {
                setBusy(false);
              }
            })();
          }}
        />
      </label>
      {notice && <p role="status">{notice}</p>}
      {onModelSettings && (
        <Button variant="outline" onClick={onModelSettings}>
          配置模型与视觉能力
        </Button>
      )}
    </section>
  );
}

export function DocumentResult({ result }: { result: Record<string, unknown> }) {
  return (
    <>
      {typeof result.summary === 'string' && <div className="work-summary">{result.summary}</div>}
      {typeof result.next_start === 'number' && (
        <p>
          后续可从第 {result.next_start} {String(result.unit ?? '位置')}继续读取。
        </p>
      )}
      {Array.isArray(result.blocks) &&
        (result.blocks as Array<{ location: string; text: string }>).map((block, index) => (
          <div key={index}>
            <strong>{block.location}</strong>
            <pre>{block.text}</pre>
          </div>
        ))}
      {Array.isArray(result.warnings) && (
        <ul>
          {result.warnings.map((warning, index) => (
            <li key={index}>{String(warning)}</li>
          ))}
        </ul>
      )}
      {result.partial === true && <p>本次结果包含未读或未识别部分，请以范围和提示为准。</p>}
      {result.preview_truncated === true && (
        <p>任务卡仅预览前 30 个内容块；实际阅读范围以任务记录为准，原文可从附件预览或下载查看。</p>
      )}
    </>
  );
}

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
