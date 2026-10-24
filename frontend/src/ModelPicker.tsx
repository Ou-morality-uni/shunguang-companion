import { useEffect, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { request, type ConnectionOptions, type ModelChoice, type ModelChoiceOut } from './api';
import { GlideSelect } from './components/ui/glide-select';

export const effortLabels: Record<string, string> = {
  default: '默认',
  off: '关闭',
  on: '开启',
  low: '低',
  medium: '中',
  high: '高',
  xhigh: '很高',
  max: '最高',
};
const optionId = (profile: string, model: string) => JSON.stringify([profile, model]);

export function ModelPicker({
  conversationId,
  disabled,
  onChange,
  onSettings,
  revision,
}: {
  conversationId: string | null;
  disabled: boolean;
  onChange: (choice: ModelChoice | undefined) => void;
  onSettings: () => void;
  revision?: object | null;
}) {
  const [connections, setConnections] = useState<ConnectionOptions[]>([]);
  const [choice, setChoice] = useState<ModelChoiceOut | null>(null);
  const [pending, setPending] = useState(false),
    [loading, setLoading] = useState(true),
    [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const groups = await request<ConnectionOptions[]>('/model-options', { signal: controller.signal });
        if (!controller.signal.aborted) setConnections(Array.isArray(groups) ? groups : []);
        const selected = await request<ModelChoiceOut | null>(
          conversationId ? `/conversations/${conversationId}/model` : '/model-default',
          { signal: controller.signal },
        );
        if (!controller.signal.aborted) {
          setChoice(selected || null);
          onChange(
            selected
              ? { profile_id: selected.profile_id, model: selected.model, effort: selected.effort }
              : undefined,
          );
        }
      } catch (failure) {
        if (!controller.signal.aborted) setError((failure as Error).message);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [conversationId, onChange, revision]);
  async function select(next: ModelChoice, efforts: string[]) {
    next = { profile_id: next.profile_id, model: next.model, effort: next.effort };
    setPending(true);
    setError('');
    try {
      const saved = conversationId
        ? await request<ModelChoiceOut>(`/conversations/${conversationId}/model`, {
            method: 'PATCH',
            body: JSON.stringify(next),
          })
        : { ...next, configured: true, efforts };
      setChoice(saved);
      onChange({ profile_id: saved.profile_id, model: saved.model, effort: saved.effort });
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setPending(false);
    }
  }
  async function refresh() {
    if (!choice) return;
    setPending(true);
    setError('');
    try {
      const group = await request<ConnectionOptions>(`/model-options/${choice.profile_id}/refresh`, {
        method: 'POST',
      });
      setConnections((current) => current.map((item) => (item.id === group.id ? group : item)));
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setPending(false);
    }
  }
  const options = connections.flatMap((group) =>
    group.models.map((model) => ({
      value: optionId(group.id, model.id),
      label: model.id,
      group: group.label,
      disabled: !group.configured,
      profile: group.id,
      model,
    })),
  );
  const selected = choice ? optionId(choice.profile_id, choice.model) : '';
  if (choice && !options.some((item) => item.value === selected))
    options.unshift({
      value: selected,
      label: `${choice.model}（当前保存）`,
      group: '当前会话',
      disabled: !choice.configured,
      profile: choice.profile_id,
      model: { id: choice.model, efforts: choice.efforts },
    });
  return (
    <div className="model-picker">
      <div className="model-picker-controls">
        <GlideSelect
          label="当前会话模型"
          value={selected}
          options={options}
          placeholder={loading ? '读取模型…' : '选择模型'}
          disabled={disabled || loading || pending || !options.length}
          onValueChange={(value) => {
            const item = options.find((entry) => entry.value === value);
            if (item)
              void select(
                { profile_id: item.profile, model: item.model.id, effort: 'default' },
                item.model.efforts,
              );
          }}
        />
        {choice && (
          <GlideSelect
            label="思考强度"
            value={choice.effort}
            options={choice.efforts.map((effort) => ({
              value: effort,
              label: effortLabels[effort] || effort,
            }))}
            disabled={disabled || pending || loading || choice.efforts.length === 1}
            onValueChange={(effort) =>
              void select({ ...choice, effort: effort as ModelChoice['effort'] }, choice.efforts)
            }
          />
        )}
        {choice && (
          <button
            type="button"
            className="icon-button"
            aria-label="刷新当前连接模型列表"
            title="从当前连接获取模型列表"
            onClick={() => void refresh()}
            disabled={disabled || pending || loading}
          >
            <RefreshCw size={13} className={pending ? 'spin' : ''} />
          </button>
        )}
        {!loading && !options.length && (
          <button type="button" className="text-button" onClick={onSettings}>
            配置模型连接
          </button>
        )}
      </div>
      {error && (
        <span className="model-picker-error" role="status">
          {error}
        </span>
      )}
    </div>
  );
}
