import { useEffect, useRef, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import {
  ArrowUpRight,
  AudioLines,
  Bell,
  Check,
  Cpu,
  Heart,
  LoaderCircle,
  Play,
  ShieldCheck,
  WandSparkles,
  Wrench,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import {
  request,
  type Conversation,
  type Features,
  type ModelSettings,
  type Provider,
  type InspectedVoiceReference,
} from './api';
import { MemorySpace, VoiceConsole, type Panel } from './Spaces';
import { useCompanionAudio } from './useAudioQueue';
import { ToolFeedback } from './Evidence';
import { CloudVoiceManager } from './CloudVoiceManager';
import { supportsLiveSpeech } from './speechStream';
import { backgroundStyles, type BackgroundStyle } from './Atmosphere';
import { GlideSelect } from './components/ui/glide-select';
import { effortLabels } from './ModelPicker';
import { ASRSettings } from './ASRSettings';
import { OfficeCapabilities } from './OfficeCapabilities';
import { FilePermissions } from './WorkSpace';

const categories = [
  { id: 'model', label: '模型连接', icon: Cpu },
  { id: 'voice', label: '声音与播放', icon: AudioLines },
  { id: 'effects', label: '沉浸光效', icon: WandSparkles },
  { id: 'tools', label: '工具服务', icon: Wrench },
  { id: 'memory', label: '长期记忆', icon: Heart },
  { id: 'reminders', label: '关怀提醒', icon: Bell },
] as const;
const cloneModel = 'mimo-v2.5-tts-voiceclone';
const defaultReferencePath = 'source/resources/voice/ye-shunguang/reference-original.mp3';
function editableFeatures(value: Features): Features {
  return {
    ...value,
    tts: {
      ...value.tts,
      model: value.tts.provider === 'mimo' ? cloneModel : value.tts.model,
      voice: value.tts.provider === 'mimo' ? '' : value.tts.voice,
      reference_path: value.tts.reference_path || defaultReferencePath,
    },
  };
}
function voiceSignature(value: Features['tts'] | undefined) {
  return JSON.stringify(
    value
      ? [
          value.provider,
          value.base_url,
          value.model,
          value.voice,
          value.resource_id,
          value.enabled,
          value.auto_play,
          value.work_prompts,
          value.use_model_key,
          value.speed,
          value.timeout,
          value.style,
          value.reference_path || defaultReferencePath,
          value.reference_id,
          value.reference_text,
          value.reference_sha256,
          value.external_reference_enabled,
        ]
      : [],
  );
}
type Props = {
  panel: Panel;
  setPanel: (value: Panel) => void;
  settings: ModelSettings | null;
  features: Features | null;
  effects: boolean;
  setEffects: (value: boolean) => void;
  reduceMotion: boolean;
  setReduceMotion: (value: boolean) => void;
  backgroundStyle: BackgroundStyle;
  setBackgroundStyle: (value: BackgroundStyle) => void;
  onModelSaved: (value: ModelSettings) => void;
  onFeaturesSaved: (value: Features) => void;
  conversations: Conversation[];
  active: string | null;
  onMemoryChanged: () => void;
  onTestReminder: () => void;
};
function Toggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="setting-toggle">
      <div>
        <strong>{label}</strong>
        {description && <p>{description}</p>}
      </div>
      <Switch aria-label={label} checked={checked} onCheckedChange={onChange} />
    </div>
  );
}

export function CompanionSettings({
  panel,
  setPanel,
  settings,
  features,
  effects,
  setEffects,
  reduceMotion,
  setReduceMotion,
  backgroundStyle,
  setBackgroundStyle,
  onModelSaved,
  onFeaturesSaved,
  conversations,
  active,
  onMemoryChanged,
  onTestReminder,
}: Props) {
  const [draft, setDraft] = useState<ModelSettings | null>(settings),
    [featureDraft, setFeatureDraft] = useState<Features | null>(features),
    [providers, setProviders] = useState<Provider[]>([]),
    [ttsProviders, setTtsProviders] = useState<Provider[]>([]),
    [models, setModels] = useState<Array<{ id: string }>>([]),
    [ttsModels, setTtsModels] = useState<Array<{ id: string }>>([]),
    [referenceInfo, setReferenceInfo] = useState<InspectedVoiceReference | null>(null),
    [referenceBusy, setReferenceBusy] = useState(false);
  const [modelKey, setModelKey] = useState(''),
    [voiceKey, setVoiceKey] = useState(''),
    [toolKey, setToolKey] = useState(''),
    [clearModelKey, setClearModelKey] = useState(false),
    [clearVoiceKey, setClearVoiceKey] = useState(false),
    [clearToolKey, setClearToolKey] = useState(false),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState('');
  const reduced = useReducedMotion();
  const opened = useRef(false),
    audio = useCompanionAudio(),
    navRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const returningFocus = useRef<HTMLElement | null>(null),
    mobileCategory = useRef<HTMLButtonElement | null>(null),
    requestLock = useRef(false);
  const referenceLock = useRef(false);
  const panelRef = useRef(panel);
  panelRef.current = panel;
  const [profiles, setProfiles] = useState<Array<ModelSettings & { id: string }>>([]);
  const [toolTestResult, setToolTestResult] = useState<Record<string, unknown> | null>(null);
  async function testSearch() {
    if (requestLock.current) return;
    requestLock.current = true;
    setBusy(true);
    setToolTestResult(null);
    setNotice('正在使用已保存配置测试一次搜索…');
    try {
      const result = await request<Record<string, unknown>>('/tools/run', {
        method: 'POST',
        body: JSON.stringify({
          name: 'web_search',
          args: { query: 'Python programming language', limit: 3 },
        }),
      });
      setToolTestResult(result);
      setNotice(
        result.ok
          ? '搜索返回真实来源，请打开核对。'
          : typeof result.message === 'string'
            ? result.message
            : '搜索未取得可用结果，请检查已保存的服务配置。',
      );
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      requestLock.current = false;
      setBusy(false);
    }
  }
  async function activateProfile(id: string) {
    if (!id) return;
    setBusy(true);
    try {
      const value = await request<ModelSettings>('/providers/activate', {
        method: 'POST',
        body: JSON.stringify({ id }),
      });
      setDraft(value);
      onModelSaved(value);
      setModelKey('');
      setClearModelKey(false);
      setModels([]);
      setNotice('已切换到保存的连接。');
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      requestLock.current = false;
      setBusy(false);
    }
  }
  useEffect(() => {
    if (panel && !opened.current) {
      opened.current = true;
      setDraft(settings ? { ...settings } : null);
      setFeatureDraft(features ? editableFeatures(structuredClone(features)) : null);
      setModelKey('');
      setVoiceKey('');
      setToolKey('');
      setClearModelKey(false);
      setClearVoiceKey(false);
      setClearToolKey(false);
      setNotice('');
      setReferenceInfo(null);
      const calls = [
        request<Provider[]>('/providers/presets').then(setProviders),
        request<Provider[] | { presets: Provider[] }>('/tts/presets').then((data) =>
          setTtsProviders(Array.isArray(data) ? data : data.presets),
        ),
        request<Features>('/features').then((value) => setFeatureDraft(editableFeatures(value))),
        request<Array<ModelSettings & { id: string }>>('/providers/profiles').then(setProfiles),
      ];
      void Promise.allSettled(calls).then((results) => {
        const failed = results.filter((item) => item.status === 'rejected');
        if (failed.length && panelRef.current) setNotice('部分设置暂时无法读取，请确认后端服务在线。');
      });
    } else if (!panel) {
      opened.current = false;
      setModelKey('');
      setVoiceKey('');
      setToolKey('');
      setReferenceInfo(null);
    }
  }, [panel, settings, features]);
  function setTts(update: Partial<Features['tts']>) {
    setFeatureDraft((previous) =>
      previous ? { ...previous, tts: { ...previous.tts, ...update } } : previous,
    );
  }
  function setTools(update: Partial<Features['tools']>) {
    if (featureDraft) setFeatureDraft({ ...featureDraft, tools: { ...featureDraft.tools, ...update } });
  }
  function setReminder(update: Partial<Features['reminders']>) {
    if (featureDraft)
      setFeatureDraft({ ...featureDraft, reminders: { ...featureDraft.reminders, ...update } });
  }
  async function discoverModels() {
    if (!draft || busy || requestLock.current) return;
    requestLock.current = true;
    setBusy(true);
    setNotice('正在读取提供商真实模型列表…');
    try {
      const result = await request<{ models: Array<{ id: string }>; notice?: string }>(
        '/providers/discover',
        {
          method: 'POST',
          body: JSON.stringify({
            provider: draft.provider || 'custom',
            protocol: draft.protocol || 'openai',
            base_url: draft.base_url,
            timeout: draft.timeout,
            api_key: modelKey.trim() || undefined,
          }),
        },
      );
      setModels(result.models);
      setNotice(result.notice || `读取到 ${result.models.length} 个模型；请选择或手动填写模型 ID。`);
    } catch (e) {
      setNotice(`${(e as Error).message} 可手动填写模型 ID。`);
    } finally {
      requestLock.current = false;
      setBusy(false);
    }
  }
  async function discoverVoice() {
    if (!featureDraft || busy || requestLock.current) return;
    requestLock.current = true;
    setBusy(true);
    setNotice('正在读取支持本地参考音频的克隆模型…');
    try {
      const result = await request<{
        models: Array<{ id: string }>;
        capabilities?: { reference_audio?: boolean };
        notice?: string;
      }>('/tts/discover', {
        method: 'POST',
        body: JSON.stringify({
          provider: featureDraft.tts.provider,
          base_url: featureDraft.tts.base_url,
          model: featureDraft.tts.model,
          voice: featureDraft.tts.voice,
          use_model_key: featureDraft.tts.use_model_key,
          api_key: voiceKey.trim() || undefined,
        }),
      });
      const supported =
        featureDraft.tts.provider === 'mimo'
          ? result.models.filter((item) => item.id === cloneModel)
          : result.models;
      setTtsModels(supported);
      setNotice(
        featureDraft.tts.provider !== 'mimo'
          ? result.notice || '已读取适配模型预设。'
          : supported.length
            ? '已发现 MiMo 参考声音克隆模型。请选择本地 MP3、保存配置后测试。'
            : '上游未列出参考声音克隆模型。保留模型 ID 供权限核对，不回退到预置音色。',
      );
    } catch (e) {
      setNotice(`${(e as Error).message} 不会回退到普通 TTS 或预置音色。`);
    } finally {
      requestLock.current = false;
      setBusy(false);
    }
  }
  async function saveModel(test = false) {
    if (!draft || requestLock.current) return;
    requestLock.current = true;
    setBusy(true);
    setNotice('');
    try {
      const value = await request<ModelSettings>('/settings', {
        method: 'PATCH',
        body: JSON.stringify({
          provider: draft.provider || 'custom',
          protocol: draft.protocol || 'openai',
          base_url: draft.base_url,
          model: draft.model,
          temperature: draft.temperature,
          timeout: draft.timeout,
          max_tokens: draft.max_tokens,
          effort: draft.effort ?? 'default',
          api_key: modelKey.trim() || undefined,
          clear_api_key: clearModelKey,
          vision: draft.vision ?? 'unknown',
        }),
      });
      setDraft(value);
      onModelSaved(value);
      setModelKey('');
      setClearModelKey(false);
      setNotice('模型配置已保存。');
      setProfiles(await request<Array<ModelSettings & { id: string }>>('/providers/profiles'));
      if (test) {
        const result = await request<{ message: string }>('/providers/test', { method: 'POST' });
        setNotice(`真实连接测试成功：${result.message}`);
      }
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      requestLock.current = false;
      setBusy(false);
    }
  }
  async function saveFeature(section: 'tts' | 'tools' | 'reminders') {
    if (!featureDraft || requestLock.current || referenceLock.current) return;
    requestLock.current = true;
    setBusy(true);
    setNotice('');
    try {
      let body: Record<string, unknown> = { ...featureDraft[section] };
      delete body.has_api_key;
      delete body.capabilities;
      delete body.configured;
      delete body.notice;
      delete body.coverage;
      delete body.reference_sha256;
      if (section === 'tts') {
        const current = featureDraft.tts;
        if (!['mimo', 'aliyun'].includes(current.provider)) throw new Error('请选择已适配的声音复刻厂商。');
        const selected =
          current.provider === 'mimo'
            ? await request<InspectedVoiceReference>('/voice/reference/inspect', {
                method: 'POST',
                body: JSON.stringify({ path: current.reference_path || defaultReferencePath }),
              })
            : null;
        if (selected) setReferenceInfo(selected);
        body = {
          enabled: !!current.enabled,
          auto_play: !!current.auto_play,
          work_prompts: current.work_prompts !== false,
          muted: !!current.muted,
          provider: current.provider,
          base_url: current.base_url,
          model: current.provider === 'mimo' ? cloneModel : current.model,
          voice: current.provider === 'mimo' ? '' : current.voice.trim(),
          resource_id: current.resource_id || 'seed-icl-2.0',
          use_model_key: !!current.use_model_key,
          timeout: current.timeout ?? 45,
          speed: current.speed ?? 1,
          style: current.style || '',
          reference_path: selected?.path || current.reference_path || defaultReferencePath,
          reference_id: selected?.id || current.reference_id,
          reference_text: current.reference_text || '',
          external_reference_enabled: !!current.external_reference_enabled,
          api_key: voiceKey.trim() || undefined,
          clear_api_key: clearVoiceKey,
        };
      }
      if (section === 'tools')
        body = { ...body, api_key: toolKey.trim() || undefined, clear_api_key: clearToolKey };
      const value = await request<Features>('/features', {
        method: 'PATCH',
        body: JSON.stringify({ [section]: body }),
      });
      setFeatureDraft(editableFeatures(value));
      onFeaturesSaved(value);
      if (section === 'tts') {
        setVoiceKey('');
        setClearVoiceKey(false);
      }
      if (section === 'tools') {
        setToolKey('');
        setClearToolKey(false);
      }
      setNotice(
        section === 'tts'
          ? '声音配置已保存。百炼按云端音色 ID 合成；小米按授权发送参考音频。'
          : '配置已保存。',
      );
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      requestLock.current = false;
      setBusy(false);
    }
  }
  async function inspectReference() {
    if (referenceLock.current) return;
    referenceLock.current = true;
    setReferenceBusy(true);
    setNotice('正在验证运行电脑上的 MP3，不会发送到外部服务…');
    try {
      const selected = await request<InspectedVoiceReference>('/voice/reference/inspect', {
        method: 'POST',
        body: JSON.stringify({ path: featureDraft?.tts.reference_path || defaultReferencePath }),
      });
      if (selected.format !== 'mp3') throw new Error('请选择 MP3 参考音频。');
      setReferenceInfo(selected);
      setTts({ reference_path: selected.path, reference_id: selected.id, reference_sha256: selected.sha256 });
      setNotice('已选择此 MP3，验证仅在本机完成。请保存配置后测试克隆声音。');
    } catch (e) {
      setReferenceInfo(null);
      setNotice((e as Error).message);
    } finally {
      referenceLock.current = false;
      setReferenceBusy(false);
    }
  }
  const tts = featureDraft?.tts,
    tools = featureDraft?.tools,
    reminders = featureDraft?.reminders;
  const referenceSupported = !!tts && ['mimo', 'aliyun'].includes(tts.provider);
  const cloneProviders = ttsProviders.filter(
    (item) => item.id === 'mimo' || item.reference_audio || item.reference_supported,
  );
  const voiceDirty =
    voiceSignature(tts) !== voiceSignature(features?.tts) || !!voiceKey.trim() || clearVoiceKey;
  const savedCloneReady = !!features?.tts.enabled && !!features.tts.configured;
  function testSavedClone() {
    if (voiceDirty) {
      setNotice('参考文件或语音设置已修改，请先保存克隆配置，再测试已保存的声音。');
      return;
    }
    if (!savedCloneReady) {
      setNotice('请先启用 TTS，保存厂商密钥与参考音频或已注册音色 ID。');
      return;
    }
    audio.enqueue('你好，忙碌之余，也记得照顾好自己。', '参考声音克隆测试');
  }
  function selectProvider(id: string) {
    const item = providers.find((value) => value.id === id);
    if (!draft || !item) return;
    const stored = profiles.find(
      (value) =>
        value.base_url.replace(/\/$/, '') === item.base_url.replace(/\/$/, '') &&
        (value.protocol || 'openai') === (item.protocol || 'openai'),
    );
    setDraft({
      ...draft,
      provider: item.id,
      base_url: item.base_url,
      protocol: item.protocol || 'openai',
      model: stored?.model || item.model || '',
      vision: stored?.vision ?? 'unknown',
      effort: stored?.effort ?? 'default',
      efforts: stored?.efforts ?? ['default'],
      has_api_key: !!stored?.has_api_key,
    });
    setModels([]);
    setModelKey('');
    setClearModelKey(false);
    setNotice(
      stored?.has_api_key
        ? '已找到此服务保存的连接，留空使用此服务的已存密钥。'
        : item.notice || '填写当前服务的密钥后读取真实模型，并选择模型 ID。',
    );
  }
  return (
    <Dialog
      open={!!panel}
      onOpenChange={(open) => {
        if (!open) setPanel(null);
      }}
    >
      <DialogContent
        className="settings-modal unified-settings"
        showCloseButton
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          returningFocus.current =
            document.activeElement instanceof HTMLElement ? document.activeElement : null;
          if (matchMedia('(max-width:700px)').matches) mobileCategory.current?.focus();
          else
            navRefs.current[
              Math.max(
                0,
                categories.findIndex((item) => item.id === panel),
              )
            ]?.focus();
        }}
        onCloseAutoFocus={(e) => {
          e.preventDefault();
          returningFocus.current?.focus();
        }}
      >
        <div className="modal-heading">
          <span className="eyebrow">YOUR COMPANION, YOUR WAY</span>
          <DialogTitle>陪伴设置</DialogTitle>
          <DialogDescription>把相伴的方式，调成你喜欢的样子。</DialogDescription>
        </div>
        <div className="settings-layout">
          <nav className="settings-nav" aria-label="设置分类" role="tablist" aria-orientation="vertical">
            {categories.map(({ id, label, icon: Icon }, index) => (
              <button
                ref={(el) => {
                  navRefs.current[index] = el;
                }}
                id={`settings-tab-${id}`}
                type="button"
                role="tab"
                aria-selected={panel === id}
                aria-controls={`settings-body-${id}`}
                tabIndex={panel === id ? 0 : -1}
                disabled={busy}
                key={id}
                className={panel === id ? 'active' : ''}
                onClick={() => {
                  setPanel(id);
                  setNotice('');
                }}
                onKeyDown={(e) => {
                  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    const next =
                      (index + (e.key === 'ArrowDown' ? 1 : -1) + categories.length) % categories.length;
                    setPanel(categories[next].id);
                    setNotice('');
                    navRefs.current[next]?.focus();
                  }
                }}
              >
                {panel === id && (
                  <motion.span
                    aria-hidden="true"
                    className="selection-glide"
                    layoutId="settings-navigation-highlight"
                    transition={{ duration: reduced || !effects || reduceMotion ? 0 : 0.22 }}
                  />
                )}
                <Icon size={18} />
                {label}
              </button>
            ))}
          </nav>
          <label className="mobile-settings-select">
            设置分类
            <GlideSelect
              ref={mobileCategory}
              label="设置分类"
              value={panel || 'model'}
              disabled={busy}
              onValueChange={(value) => {
                setPanel(value as Panel);
                setNotice('');
              }}
              options={categories.map((item) => ({ value: item.id, label: item.label }))}
            />
          </label>
          <section
            className="settings-body"
            role="tabpanel"
            id={`settings-body-${panel}`}
            aria-labelledby={`settings-tab-${panel}`}
            tabIndex={0}
          >
            {panel === 'model' && profiles.length > 0 && (
              <label className="field">
                已保存的连接
                <GlideSelect
                  label="已保存的连接"
                  placeholder="选择并激活保存的连接"
                  value=""
                  disabled={busy}
                  onValueChange={(value) => void activateProfile(value)}
                  options={profiles.map((item) => ({
                    value: item.id,
                    label: `${item.provider || item.base_url} · ${item.protocol || 'openai'} · ${item.model}`,
                  }))}
                />
              </label>
            )}
            {panel === 'model' &&
              (draft ? (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void saveModel();
                  }}
                >
                  <h2>模型连接</h2>
                  <label className="field">
                    提供商
                    <GlideSelect
                      label="提供商"
                      value={draft.provider || 'custom'}
                      onValueChange={selectProvider}
                      options={[
                        ...providers.map((item) => ({ value: item.id, label: item.name })),
                        ...(!providers.some((item) => item.id === (draft.provider || 'custom'))
                          ? [{ value: draft.provider || 'custom', label: '当前自定义配置' }]
                          : []),
                      ]}
                    />
                  </label>
                  <details className="reference-panel" open={draft.provider === 'custom' || undefined}>
                    <summary>接口地址与协议</summary>
                    <label className="field">
                      接口协议
                      <GlideSelect
                        label="接口协议"
                        value={draft.protocol || 'openai'}
                        onValueChange={(value) =>
                          setDraft({
                            ...draft,
                            protocol: value as 'openai' | 'anthropic',
                            vision: 'unknown',
                            effort: 'default',
                            efforts: ['default'],
                          })
                        }
                        options={[
                          { value: 'openai', label: 'OpenAI 兼容' },
                          { value: 'anthropic', label: 'Anthropic 兼容' },
                        ]}
                      />
                      <span className="field-hint">协议决定请求和流式解析方式，请匹配提供商的实际接口。</span>
                    </label>
                    <label className="field">
                      API 地址
                      <Input
                        aria-label="模型 API 地址"
                        type="url"
                        required
                        value={draft.base_url}
                        onChange={(e) =>
                          setDraft({
                            ...draft,
                            base_url: e.target.value,
                            vision: 'unknown',
                            effort: 'default',
                            efforts: ['default'],
                            has_api_key: e.target.value === settings?.base_url && !!settings.has_api_key,
                          })
                        }
                        maxLength={500}
                      />
                    </label>
                  </details>
                  <label className="field">
                    API 密钥
                    <Input
                      aria-label="模型 API 密钥"
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      value={modelKey}
                      disabled={clearModelKey || busy}
                      onChange={(e) => setModelKey(e.target.value)}
                      onBlur={() => {
                        if (modelKey.trim()) void discoverModels();
                      }}
                      placeholder={
                        clearModelKey
                          ? '保存后移除已存密钥'
                          : draft.has_api_key
                            ? '已保存当前服务密钥；留空保留，填写替换'
                            : '填写当前提供商的 API Key'
                      }
                      maxLength={2048}
                    />
                    <span className="field-hint">密钥由后端加密保存，已有密钥不会回显。</span>
                  </label>
                  {draft.has_api_key && (
                    <button
                      className="clear-key"
                      type="button"
                      onClick={() => {
                        setClearModelKey((v) => !v);
                        setModelKey('');
                      }}
                    >
                      {clearModelKey ? '取消移除密钥' : '明确移除已保存密钥'}
                    </button>
                  )}
                  <div className="discovery-row">
                    <Button
                      type="button"
                      variant="outline"
                      disabled={busy || clearModelKey}
                      onClick={() => void discoverModels()}
                    >
                      <SearchIcon />
                      读取可用模型
                    </Button>
                    <span>无列表权限时可手动填写</span>
                  </div>
                  {models.length > 0 && (
                    <label className="field">
                      可用模型
                      <GlideSelect
                        label="可用模型"
                        placeholder="选择实际模型"
                        value={models.some((item) => item.id === draft.model) ? draft.model : ''}
                        onValueChange={(value) =>
                          setDraft({
                            ...draft,
                            model: value,
                            vision: 'unknown',
                            effort: 'default',
                            efforts: ['default'],
                          })
                        }
                        options={models.map((item) => ({ value: item.id, label: item.id }))}
                      />
                    </label>
                  )}
                  <label className="field">
                    模型 ID
                    <Input
                      aria-label="模型 ID"
                      required
                      value={draft.model}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          model: e.target.value,
                          vision: 'unknown',
                          effort: 'default',
                          efforts: ['default'],
                        })
                      }
                      maxLength={150}
                    />
                  </label>
                  <details className="model-advanced reference-panel">
                    <summary>模型高级设置</summary>
                    {(draft.efforts || []).some((value) => value !== 'default') && (
                      <>
                        <label className="field">
                          新聊天的默认思考强度
                          <GlideSelect
                            label="新聊天的默认思考强度"
                            value={draft.effort || 'default'}
                            options={(draft.efforts || [])
                              .filter((value) => value !== 'default')
                              .map((value) => ({
                                value,
                                label: effortLabels[value] || value,
                              }))}
                            disabled={busy || (draft.efforts || ['default']).length === 1}
                            onValueChange={(effort) => setDraft({ ...draft, effort })}
                          />
                          <span className="field-hint">
                            保存连接后显示已核实的支持项；不改变已有聊天的选择。
                          </span>
                        </label>
                      </>
                    )}
                    <div className="field-row">
                      <label className="field">
                        温度
                        <Input
                          type="number"
                          min={0}
                          max={2}
                          step={0.1}
                          value={draft.temperature}
                          onChange={(e) => setDraft({ ...draft, temperature: Number(e.target.value) })}
                        />
                      </label>
                      <label className="field">
                        超时（秒）
                        <Input
                          type="number"
                          min={5}
                          max={120}
                          value={draft.timeout}
                          onChange={(e) => setDraft({ ...draft, timeout: Number(e.target.value) })}
                        />
                      </label>
                    </div>
                    <label className="field">
                      最大输出 Token
                      <Input
                        type="number"
                        min={128}
                        max={8192}
                        value={draft.max_tokens}
                        onChange={(e) => setDraft({ ...draft, max_tokens: Number(e.target.value) })}
                      />
                      <span className="field-hint">更长的输出可能增加费用。请求失败不会自动重试。</span>
                    </label>
                    <label className="field">
                      当前模型的图像理解能力
                      <GlideSelect
                        label="当前模型的图像理解能力"
                        value={draft.vision ?? 'unknown'}
                        onValueChange={(value) =>
                          setDraft({ ...draft, vision: value as ModelSettings['vision'] })
                        }
                        options={[
                          { value: 'unknown', label: '尚未确认（需要替代识别时询问）' },
                          { value: 'supported', label: '已确认支持（必要图像直接交给当前模型）' },
                          { value: 'unsupported', label: '不支持图像输入' },
                        ]}
                      />
                      <span className="field-hint">
                        仅看图能力，不代表支持生图或改图。切换模型、协议或地址后需要重新确认。
                      </span>
                    </label>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={busy}
                      onClick={() => {
                        if (
                          draft.model !== settings?.model ||
                          draft.base_url !== settings?.base_url ||
                          draft.protocol !== settings?.protocol ||
                          modelKey ||
                          clearModelKey
                        ) {
                          setNotice('请先保存当前模型配置，再测试图像理解。');
                          return;
                        }
                        setBusy(true);
                        setNotice('正在用测试图片验证当前已保存模型，可能产生服务调用费用。');
                        void request<{ settings: ModelSettings; message: string }>('/work/vision/probe', {
                          method: 'POST',
                        })
                          .then((result) => {
                            setDraft(result.settings);
                            onModelSaved(result.settings);
                            setNotice(result.message);
                            return request<Array<ModelSettings & { id: string }>>('/providers/profiles').then(
                              setProfiles,
                            );
                          })
                          .catch((error: Error) => setNotice(error.message))
                          .finally(() => setBusy(false));
                      }}
                    >
                      测试图像理解（调用已保存模型）
                    </Button>
                  </details>
                  <div className="key-note">
                    <ShieldCheck size={19} />
                    <p>调用会把对话和必要上下文发送给你选择的模型服务。密钥只用于该服务，不保存到浏览器。</p>
                  </div>
                  <div className="modal-actions">
                    <Button
                      type="button"
                      variant="outline"
                      disabled={busy || clearModelKey || !draft.model.trim()}
                      onClick={() => void saveModel(true)}
                    >
                      <ArrowUpRight size={15} />
                      保存并测试连接
                    </Button>
                    <Button type="submit" disabled={busy} aria-busy={busy}>
                      <Check size={15} />
                      保存配置
                    </Button>
                  </div>
                </form>
              ) : (
                <p>模型设置需要后端服务在线。</p>
              ))}
            {panel === 'voice' && (
              <ASRSettings value={features?.asr} connections={profiles} onSaved={onFeaturesSaved} />
            )}
            {panel === 'voice' && tts && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void saveFeature('tts');
                }}
              >
                <h2>声音与播放</h2>
                <fieldset
                  disabled={busy || referenceBusy}
                  style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
                >
                  <p className="space-note">小米使用本地参考音频；百炼使用已注册的云端音色 ID。</p>
                  <Toggle
                    label="开启 TTS"
                    checked={!!tts.enabled}
                    onChange={(enabled) => setTts({ enabled })}
                  />
                  <Toggle
                    label="自动朗读新回复"
                    description={
                      tts.provider === 'aliyun'
                        ? supportsLiveSpeech(tts.model)
                          ? '文字生成时持续追加到同一个百炼任务，短暂预缓冲后连续播放。开始新回复或停止时会清空旧语音。'
                          : '当前兼容模型等待整条回复完成后朗读。开始新回复或停止时会清空旧语音。'
                        : '回复生成时合并短句朗读。开始新回复或停止时会清空旧语音。'
                    }
                    checked={!!tts.auto_play}
                    onChange={(auto_play) => setTts({ auto_play })}
                  />
                  <Toggle
                    label="工作语音提示"
                    description="开始、等待授权和完成等真实状态下自然说一句；与正文自动朗读分别控制，静音时不播放。"
                    checked={tts.work_prompts !== false}
                    onChange={(work_prompts) => setTts({ work_prompts })}
                  />
                  <label className="field">
                    语音提供商
                    <GlideSelect
                      label="语音提供商"
                      value={tts.provider}
                      disabled={busy || referenceBusy}
                      onValueChange={(id) => {
                        const item = cloneProviders.find((value) => value.id === id);
                        if (!item) return;
                        setBusy(true);
                        void request<{ tts: Features['tts'] | null }>(
                          `/tts/profile?provider=${encodeURIComponent(id)}&base_url=${encodeURIComponent(item.base_url)}`,
                        )
                          .then((stored) => {
                            setTts(
                              stored.tts || {
                                provider: id,
                                base_url: item.base_url,
                                model: item.model || '',
                                voice: '',
                                use_model_key: false,
                                external_reference_enabled: false,
                                has_api_key: false,
                              },
                            );
                            setVoiceKey('');
                            setClearVoiceKey(false);
                            setTtsModels([]);
                            setNotice(
                              stored.tts?.has_api_key
                                ? '已恢复此厂商的配置，留空保留对应密钥；请保存后使用。'
                                : item.notice || '请填写该厂商的密钥。',
                            );
                          })
                          .catch((error: Error) => setNotice(error.message))
                          .finally(() => setBusy(false));
                      }}
                      options={[
                        ...cloneProviders.map((item) => ({ value: item.id, label: item.name })),
                        ...(!cloneProviders.some((item) => item.id === 'mimo')
                          ? [{ value: 'mimo', label: '小米 MiMo · 参考音频克隆' }]
                          : []),
                        ...(tts.provider !== 'mimo' &&
                        !cloneProviders.some((item) => item.id === tts.provider)
                          ? [{ value: tts.provider, label: `${tts.provider}（须支持本项目的参考克隆）` }]
                          : []),
                      ]}
                    />
                    <span className="field-hint">
                      百炼使用云端音色实时合成；小米引用原 MP3
                      并合并短句合成。切换厂商后请使用对应密钥和音色。
                    </span>
                  </label>
                  <label className="field">
                    API 地址
                    <Input
                      aria-label="语音 API 地址"
                      type="url"
                      required
                      value={tts.base_url}
                      onChange={(e) =>
                        setTts({
                          base_url: e.target.value,
                          has_api_key:
                            e.target.value === features?.tts.base_url && !!features?.tts.has_api_key,
                        })
                      }
                    />
                  </label>
                  {tts.provider === 'mimo' && (
                    <Toggle
                      label="复用已保存的小米模型密钥"
                      description="只在小米官方同地址接口复用后端保存的密钥。"
                      checked={!!tts.use_model_key}
                      onChange={(use_model_key) => setTts({ use_model_key })}
                    />
                  )}
                  <label className="field">
                    语音 API 密钥
                    <Input
                      aria-label="语音 API 密钥"
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      value={voiceKey}
                      disabled={clearVoiceKey || busy}
                      onChange={(e) => setVoiceKey(e.target.value)}
                      placeholder={
                        tts.has_api_key ? '已保存；留空保留，填写替换' : '填写该厂商的语音 API Key'
                      }
                      maxLength={2048}
                    />
                  </label>
                  {tts.has_api_key && (
                    <button
                      className="clear-key"
                      type="button"
                      onClick={() => {
                        setClearVoiceKey((v) => !v);
                        setVoiceKey('');
                      }}
                    >
                      {clearVoiceKey ? '取消移除密钥' : '明确移除语音密钥'}
                    </button>
                  )}
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy || clearVoiceKey}
                    onClick={() => void discoverVoice()}
                  >
                    <SearchIcon />
                    {tts.provider === 'mimo' ? '读取参考克隆模型' : '查看已适配模型'}
                  </Button>
                  {ttsModels.length > 0 && (
                    <p className="space-note" role="status">
                      已发现：{ttsModels.map((item) => item.id).join('、')}
                    </p>
                  )}
                  <label className="field">
                    TTS 克隆模型 ID
                    {tts.provider === 'aliyun' ? (
                      <GlideSelect
                        label="TTS 克隆模型 ID"
                        value={tts.model}
                        onValueChange={(value) => setTts({ model: value, voice: '' })}
                        options={[
                          ...(![
                            'qwen-audio-3.1-tts-flash',
                            'qwen-audio-3.0-tts-flash',
                            'qwen-audio-3.0-tts-plus',
                          ].includes(tts.model) && tts.model
                            ? [{ value: tts.model, label: `${tts.model}（旧配置，请核对）` }]
                            : []),
                          { value: 'qwen-audio-3.1-tts-flash', label: 'Qwen-Audio 3.1 Flash' },
                          { value: 'qwen-audio-3.0-tts-flash', label: 'Qwen-Audio 3.0 Flash' },
                          { value: 'qwen-audio-3.0-tts-plus', label: 'Qwen-Audio 3.0 Plus' },
                        ]}
                      />
                    ) : (
                      <Input
                        aria-label="TTS 克隆模型 ID"
                        readOnly={tts.provider === 'mimo'}
                        onChange={(e) => setTts({ model: e.target.value })}
                        value={tts.provider === 'mimo' ? cloneModel : tts.model}
                      />
                    )}
                    <span className="field-hint">
                      音色必须与合成模型、账号及地域匹配；预设列表不代表账号权限验证。
                    </span>
                  </label>
                  {tts.provider === 'aliyun' && features && (
                    <CloudVoiceManager
                      key={tts.base_url + tts.model}
                      dirty={voiceDirty}
                      features={features}
                      onSaved={(next) => {
                        setFeatureDraft(editableFeatures(next));
                        onFeaturesSaved(next);
                      }}
                    />
                  )}
                  {tts.provider !== 'mimo' && (
                    <label className="field">
                      克隆音色 ID
                      <Input
                        aria-label="克隆音色 ID"
                        value={tts.voice}
                        maxLength={150}
                        onChange={(e) => setTts({ voice: e.target.value })}
                        placeholder="已创建的 Qwen voice ID"
                      />
                      <span className="field-hint">合成时只发送文字和音色 ID，无需重复上传 MP3。</span>
                    </label>
                  )}
                  {!referenceSupported && (
                    <p className="settings-notice" role="status">
                      当前提供商未适配，请选择小米或百炼声音复刻服务。
                    </p>
                  )}
                  <label className="field">
                    播放速度
                    <Input
                      type="number"
                      min={0.25}
                      max={4}
                      step={0.05}
                      value={tts.speed ?? 1}
                      onChange={(e) => setTts({ speed: Number(e.target.value) })}
                    />
                  </label>
                  {referenceSupported && (
                    <>
                      <div className="reference-panel local-reference-picker">
                        <h3>选择本地参考音频</h3>
                        <label className="field">
                          参考 MP3 路径
                          <Input
                            aria-label="参考 MP3 路径"
                            disabled={busy || referenceBusy}
                            required
                            value={tts.reference_path ?? defaultReferencePath}
                            onChange={(e) => {
                              setReferenceInfo(null);
                              setTts({
                                reference_path: e.target.value,
                                reference_id: '',
                                reference_sha256: undefined,
                              });
                            }}
                            placeholder={defaultReferencePath}
                            maxLength={1200}
                          />
                          <span className="field-hint">
                            相对路径从项目目录定位，也可填写运行服务电脑上的绝对路径。小米仅引用该文件；百炼也可在云端音色区临时选择
                            MP3 创建。
                          </span>
                        </label>
                        <div className="inline-actions">
                          <Button
                            type="button"
                            variant="outline"
                            disabled={referenceBusy || busy || !tts.reference_path?.trim()}
                            onClick={() => void inspectReference()}
                          >
                            验证电脑上的 MP3
                          </Button>
                        </div>
                        <div className="reference-selected" role="status">
                          {referenceBusy ? (
                            <>
                              <LoaderCircle size={16} className="spin" />
                              正在本机验证 MP3…
                            </>
                          ) : referenceInfo ? (
                            <>
                              <Check size={16} />
                              <span>
                                已选中：{referenceInfo.name}
                                <small>
                                  {referenceInfo.format.toUpperCase()} ·{' '}
                                  {(referenceInfo.bytes / 1024 / 1024).toFixed(2)} MB
                                  {Number.isFinite(referenceInfo.duration)
                                    ? ` · ${referenceInfo.duration.toFixed(1)} 秒`
                                    : ''}
                                  <br />
                                  {referenceInfo.path}
                                </small>
                              </span>
                            </>
                          ) : (
                            <span>
                              {tts.reference_id
                                ? '当前已保存的参考 MP3 路径'
                                : '路径已填写，验证或选择 MP3 后确认'}
                              <small>{tts.reference_path || defaultReferencePath}</small>
                            </span>
                          )}
                        </div>
                        <p className="space-note">
                          音频最多 6
                          MB。路径验证只在本机执行，不复制文件、不创建参考目录。百炼创建成功后不再依赖此路径。
                        </p>
                      </div>
                      <Toggle
                        label={tts.provider === 'aliyun' ? '允许创建云端克隆音色' : '允许合成时发送参考音频'}
                        description={
                          tts.provider === 'aliyun'
                            ? '保存此开关不会上传。点击创建音色后会将所选音频发送给阿里云，可能产生厂商费用；已有音色 ID 可直接填写。'
                            : '开启并保存后，每次合成会将所选音频发送给小米用于参考声音克隆。'
                        }
                        checked={!!tts.external_reference_enabled}
                        onChange={(external_reference_enabled) => setTts({ external_reference_enabled })}
                      />
                      {tts.provider === 'aliyun' && (
                        <>
                          <label className="field">
                            参考音频文字（选填）
                            <Input
                              value={tts.reference_text || ''}
                              maxLength={2000}
                              onChange={(e) => setTts({ reference_text: e.target.value })}
                            />
                          </label>
                        </>
                      )}
                    </>
                  )}
                  <VoiceConsole />
                  <p className="space-note">
                    {voiceDirty
                      ? '参考文件或设置已修改，请先保存克隆配置。测试不会使用之前的普通 TTS 配置。'
                      : savedCloneReady
                        ? '测试会使用已保存的厂商与克隆音色配置，可能产生语音服务费用。'
                        : '请启用 TTS 并保存有效密钥、参考音频或云端音色 ID，之后即可测试。'}
                  </p>
                  <div className="modal-actions">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={testSavedClone}
                      disabled={busy || referenceBusy || voiceDirty || !savedCloneReady}
                    >
                      使用已保存配置测试克隆声音
                    </Button>
                    <Button type="submit" disabled={busy || referenceBusy || !referenceSupported}>
                      <Check size={15} />
                      保存克隆声音配置
                    </Button>
                  </div>
                </fieldset>
              </form>
            )}
            {panel === 'effects' && (
              <>
                <h2>沉浸光效</h2>
                <fieldset className="background-choices">
                  <legend>背景光效</legend>
                  {backgroundStyles.map((item) => (
                    <label key={item.id} className="background-choice">
                      {backgroundStyle === item.id && (
                        <motion.span
                          aria-hidden="true"
                          className="selection-glide"
                          layoutId="background-style-highlight"
                          transition={{ duration: reduced || !effects || reduceMotion ? 0 : 0.22 }}
                        />
                      )}
                      <input
                        type="radio"
                        name="background-style"
                        value={item.id}
                        checked={backgroundStyle === item.id}
                        onChange={() => setBackgroundStyle(item.id)}
                      />
                      <span>
                        <strong>{item.name}</strong>
                        <small>{item.description}</small>
                      </span>
                    </label>
                  ))}
                </fieldset>
                <Toggle
                  label="沉浸光效"
                  description="所选背景在全区域响应鼠标，卡片带局部柔光；正文遮罩保持清晰，触屏保留静态霞光。"
                  checked={effects}
                  onChange={setEffects}
                />
                <Toggle
                  label="减少动态效果"
                  description="减少界面动画与鼠标效果，也尊重系统的减少动态偏好。"
                  checked={reduceMotion}
                  onChange={setReduceMotion}
                />
                <p className="space-note">
                  此设备的显示偏好自动保存。页面进入后台时暂停动效，也尊重系统的减少动态效果设置。
                </p>
                <div className="about-app">
                  <h3>关于瞬光伴行</h3>
                  <p>
                    这是以《绝区零》叶瞬光为原型的非官方 AI 陪伴 Web
                    应用。对话由你配置的模型生成，资料检索、天气、搜索、记忆与语音按实际配置使用。AI
                    回答可能有误，角色素材归原权利方所有。
                  </p>
                  <p>聊天、确认记忆与加密配置保存在运行服务的电脑；模型和工具请求按所选服务处理。</p>
                </div>
              </>
            )}
            {panel === 'tools' && <FilePermissions />}
            {panel === 'tools' && tools && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void saveFeature('tools');
                }}
              >
                <h2>工具服务</h2>
                <OfficeCapabilities />
                <Toggle
                  label="天气查询"
                  description="真实天气服务；请在对话中写明城市，缺失或存在歧义时会澄清。"
                  checked={tools.weather_enabled}
                  onChange={(weather_enabled) => setTools({ weather_enabled })}
                />
                <Toggle
                  label="网页搜索"
                  description="查询结果会返回可打开的来源；工具调用过程显示在对话中。"
                  checked={tools.search_enabled}
                  onChange={(search_enabled) => setTools({ search_enabled })}
                />
                <label className="field">
                  搜索服务
                  <GlideSelect
                    label="搜索服务"
                    value={tools.search_provider}
                    onValueChange={(value) => setTools({ search_provider: value })}
                    options={[
                      { value: 'public', label: '公开搜索（无需 Key）' },
                      { value: 'bing', label: 'Bing RSS（公开网页检索，尽力服务）' },
                      { value: 'wikipedia', label: 'Wikipedia（公开百科检索）' },
                      { value: 'tavily', label: 'Tavily（网页搜索，需要密钥）' },
                    ]}
                  />
                  <span className="field-hint">
                    公开搜索无需 Key，以 DuckDuckGo 为主，Bing RSS 最多一次回退，仍为尽力服务。Wikipedia
                    只提供百科内容；Tavily 需密钥。
                  </span>
                </label>
                {tools.search_provider === 'tavily' && (
                  <>
                    <label className="field">
                      搜索 API 密钥
                      <Input
                        aria-label="搜索 API 密钥"
                        type="password"
                        autoComplete="off"
                        spellCheck={false}
                        value={toolKey}
                        disabled={clearToolKey || busy}
                        onChange={(e) => setToolKey(e.target.value)}
                        placeholder={
                          tools.has_api_key
                            ? '已保存；留空保留，填写替换'
                            : '填写 Tavily API Key（通常以 tvly- 开头）'
                        }
                      />
                    </label>
                    {tools.has_api_key && (
                      <button
                        className="clear-key"
                        type="button"
                        onClick={() => {
                          setClearToolKey((v) => !v);
                          setToolKey('');
                        }}
                      >
                        {clearToolKey ? '取消移除搜索密钥' : '明确移除搜索密钥'}
                      </button>
                    )}
                  </>
                )}
                <label className="field">
                  工具超时（秒）
                  <Input
                    type="number"
                    min={3}
                    max={30}
                    value={tools.timeout ?? 12}
                    onChange={(e) => setTools({ timeout: Number(e.target.value) })}
                  />
                </label>
                <p className="space-note">
                  开启工具后，模型可在有限调用次数内选择并执行。失败原因会显示，未返回结果时不会冒充调用成功。
                </p>
                <Button type="submit" disabled={busy} aria-busy={busy}>
                  <Check size={15} />
                  保存工具配置
                </Button>
                <div className="search-connection-test">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy}
                    aria-busy={busy}
                    onClick={() => void testSearch()}
                  >
                    {busy && <LoaderCircle size={15} className="spin" />}测试搜索连接
                  </Button>
                  <span className="field-hint">使用已保存的配置测试一次搜索。</span>
                  {toolTestResult && (
                    <ToolFeedback
                      tools={[
                        {
                          id: 'settings-search-test',
                          name: 'web_search',
                          status: toolTestResult.ok ? 'complete' : 'error',
                          result: toolTestResult,
                        },
                      ]}
                    />
                  )}
                </div>
              </form>
            )}
            {panel === 'memory' && (
              <>
                <h2>长期记忆</h2>
                <p className="space-note">
                  自动记忆基于明确自述，手动总结作为补充。你可以随时修改、删除或暂停自动记忆。
                </p>
                {features && (
                  <div className="reference-panel">
                    <Toggle
                      label="自动记忆用户事实"
                      description="根据明确自述自动保存；记忆仍可查看、更正与删除。"
                      checked={features.memory?.auto_save ?? true}
                      onChange={(auto_save) =>
                        void request<Features>('/features', {
                          method: 'PATCH',
                          body: JSON.stringify({ memory: { auto_save } }),
                        })
                          .then(onFeaturesSaved)
                          .catch((error: Error) => setNotice(error.message))
                      }
                    />
                    <Toggle
                      label="跨聊天回忆"
                      description="允许读取同一资料空间的真实聊天经历。"
                      checked={features.memory?.recall_history ?? true}
                      onChange={(recall_history) =>
                        void request<Features>('/features', {
                          method: 'PATCH',
                          body: JSON.stringify({ memory: { recall_history } }),
                        })
                          .then(onFeaturesSaved)
                          .catch((error: Error) => setNotice(error.message))
                      }
                    />
                  </div>
                )}
                <MemorySpace
                  compact
                  conversations={conversations}
                  active={active}
                  onChanged={onMemoryChanged}
                />
              </>
            )}
            {panel === 'reminders' && reminders && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void saveFeature('reminders');
                }}
              >
                <h2>关怀提醒</h2>
                <Toggle
                  label="开启休息提醒"
                  checked={reminders.enabled}
                  onChange={(enabled) => setReminder({ enabled })}
                />
                <label className="field">
                  间隔（分钟）
                  <Input
                    type="number"
                    required
                    min={1}
                    max={480}
                    value={reminders.interval_minutes}
                    onChange={(e) => setReminder({ interval_minutes: Number(e.target.value) })}
                  />
                </label>
                <div className="field-row">
                  <label className="field">
                    安静时段开始
                    <Input
                      type="time"
                      value={reminders.quiet_start}
                      onChange={(e) => setReminder({ quiet_start: e.target.value })}
                    />
                  </label>
                  <label className="field">
                    安静时段结束
                    <Input
                      type="time"
                      value={reminders.quiet_end}
                      onChange={(e) => setReminder({ quiet_end: e.target.value })}
                    />
                  </label>
                </div>
                <label className="field">
                  时区
                  <Input
                    value={reminders.timezone}
                    onChange={(e) => setReminder({ timezone: e.target.value })}
                  />
                </label>
                <Toggle
                  label="语音提醒"
                  description="需要已启用并配置 TTS；播放可能受浏览器后台限制。"
                  checked={reminders.voice}
                  onChange={(voice) => setReminder({ voice })}
                />
                <div className="inline-actions">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() =>
                      setReminder({
                        paused_until: reminders.paused_until
                          ? null
                          : new Date(Date.now() + 3600000).toISOString(),
                      })
                    }
                  >
                    {reminders.paused_until ? '恢复提醒' : '暂停一小时（保存生效）'}
                  </Button>
                  <Button type="button" variant="outline" onClick={onTestReminder}>
                    <Play size={15} />
                    立即测试
                  </Button>
                </div>
                {reminders.paused_until && (
                  <p className="space-note">
                    暂停到 {new Date(reminders.paused_until).toLocaleString('zh-CN')}
                  </p>
                )}
                <p className="space-note">
                  按时间间隔触发，不检测坐姿。页面需打开并连接服务；后台可能延迟，浏览器关闭后不能保证提醒。重连不补发积压提醒。
                </p>
                <Button type="submit" disabled={busy} aria-busy={busy}>
                  <Check size={15} />
                  保存提醒配置
                </Button>
              </form>
            )}
            {!featureDraft && panel !== 'model' && panel !== 'effects' && panel !== 'memory' && (
              <p>服务配置暂未读取，请关闭后重试。</p>
            )}
            {busy && (
              <div className="settings-progress" role="status">
                <LoaderCircle className="spin" size={16} />
                请求处理中…
              </div>
            )}
            {notice && (
              <div className="settings-notice" role="status">
                {notice}
              </div>
            )}
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
function SearchIcon() {
  return <ArrowUpRight size={15} />;
}
