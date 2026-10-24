import { useEffect, useRef, useState } from 'react';
import {
  BookOpen,
  Check,
  Clock3,
  Heart,
  LoaderCircle,
  Pause,
  Play,
  Search,
  ShieldCheck,
  Square,
  Trash2,
  Volume2,
  VolumeX,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  request,
  type Conversation,
  type Features,
  type Memory,
  type RagStatus,
  type ReminderEvent,
  type Source,
} from './api';
import { Sources } from './Evidence';
import { UserProfileForm } from './UserProfileForm';
import { useCompanionAudio } from './useAudioQueue';

export type Page = 'chat' | 'memory' | 'world' | 'reminders' | 'work';
export type Panel = 'model' | 'voice' | 'effects' | 'tools' | 'memory' | 'reminders' | null;
function PageHeading({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div className="page-heading">
      <span className="eyebrow">{eyebrow}</span>
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
  );
}

export function VoiceConsole({ compact = false }: { compact?: boolean }) {
  const audio = useCompanionAudio(),
    canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const ctx = el.getContext('2d');
    if (!ctx) return;
    let frame = 0;
    const draw = () => {
      ctx.clearRect(0, 0, el.width, el.height);
      const data = new Uint8Array(audio.analyser?.frequencyBinCount || 64);
      audio.analyser?.getByteTimeDomainData(data);
      ctx.strokeStyle = '#e5bd8d';
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i < data.length; i++) {
        const y = audio.playing ? (data[i] / 255) * el.height : el.height / 2;
        const x = (i / (data.length - 1)) * el.width;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      if (audio.playing && !document.hidden) frame = requestAnimationFrame(draw);
    };
    draw();
    const visible = () => {
      cancelAnimationFrame(frame);
      draw();
    };
    document.addEventListener('visibilitychange', visible);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [audio.analyser, audio.playing]);
  const time = (seconds: number) =>
    `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60)
      .toString()
      .padStart(2, '0')}`;
  return (
    <div className={`voice-console ${compact ? 'compact' : ''}`}>
      <canvas
        ref={canvas}
        className="audio-wave"
        width={500}
        height={70}
        aria-label={audio.playing ? '实际音频波形' : '无音频播放'}
        role="img"
      />
      <div className="voice-controls">
        <button
          type="button"
          className="voice-play"
          onClick={audio.stop}
          disabled={!audio.busy}
          aria-label="停止语音"
        >
          <Square size={15} />
        </button>
        <span>
          {audio.busy ? (audio.playing ? '正在播放' : '正在合成') : '让关心，听得见'}
          <small>
            {audio.busy ? audio.label : '点击回复下方播放'}
            {audio.queued > 0 ? ` · 排队 ${audio.queued} 条` : ''}
            {audio.firstAudioMs !== null ? ` · 首音约 ${(audio.firstAudioMs / 1000).toFixed(2)} 秒` : ''}
          </small>
        </span>
        <span className="voice-time">
          {time(audio.progress)} / {time(audio.duration)}
        </span>
      </div>
      <div className="inline-actions">
        <button type="button" className="text-link" onClick={audio.replay}>
          <Play size={14} />
          重播上一条
        </button>
        <button type="button" className="text-link" onClick={audio.toggleMute}>
          {audio.muted ? <VolumeX size={14} /> : <Volume2 size={14} />} {audio.muted ? '取消静音' : '静音'}
        </button>
      </div>
      {audio.error && (
        <p className="settings-notice" role="status">
          {audio.error}
        </p>
      )}
      {!compact && (
        <p className="space-note">
          合成与播放按队列顺序进行。停止会清空队列。浏览器可能需要先点击播放；语音失败时文字聊天仍然可用。
        </p>
      )}
    </div>
  );
}

type MemoryProps = {
  conversations: Conversation[];
  active: string | null;
  onChanged?: () => void;
  compact?: boolean;
};
export function MemorySpace({ onChanged, compact = false }: MemoryProps) {
  const [memories, setMemories] = useState<Memory[]>([]),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState(''),
    [editing, setEditing] = useState<string | null>(null),
    [editValue, setEditValue] = useState(''),
    [deleting, setDeleting] = useState<string | null>(null),
    [progress, setProgress] = useState<{
      queued: number;
      running: number;
      failed: number;
      paused: number;
      summaries: number;
    } | null>(null);
  async function load() {
    setMemories(await request<Memory[]>('/memories'));
  }
  useEffect(() => {
    let disposed = false;
    const refresh = async () => {
      if (document.hidden || disposed) return;
      try {
        const [items, status] = await Promise.all([
          request<Memory[]>('/memories'),
          request<NonNullable<typeof progress>>('/memories/status'),
        ]);
        if (!disposed) {
          setMemories(items);
          setProgress(status);
        }
      } catch (e) {
        if (!disposed) setNotice((e as Error).message);
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    const visible = () => void refresh();
    document.addEventListener('visibilitychange', visible);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', visible);
    };
  }, []);
  async function update(item: Memory) {
    setBusy(true);
    try {
      await request(`/memories/${item.id}`, { method: 'PATCH', body: JSON.stringify({ value: editValue }) });
      setEditing(null);
      await load();
      onChanged?.();
      setNotice('记忆已更新。');
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function remove(id: string) {
    setBusy(true);
    try {
      await request(`/memories/${id}`, { method: 'DELETE' });
      setDeleting(null);
      await load();
      onChanged?.();
      setNotice('已删除，之后的对话不再注入这条事实。');
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={compact ? 'memory-settings-content' : 'space-page'}>
      {!compact && (
        <>
          <PageHeading
            eyebrow="LITTLE THINGS ABOUT YOU"
            title="关于你的，慢慢记住。"
            description="明确自述可自动记住，跨聊天按需回忆。这里可填写个人资料，查看、更正和删除记忆。"
          />
          <div className="summary-stats">
            <div>
              <strong>{memories.length}</strong>
              <span>已保存的记忆</span>
            </div>
            <div>
              <Heart size={23} />
              <span>你决定哪些值得记住</span>
            </div>
          </div>
        </>
      )}
      <UserProfileForm
        revision={memories.map((item) => `${item.id}:${item.value}`).join('|')}
        onSaved={async () => {
          await load();
          onChanged?.();
        }}
      />
      {progress && typeof progress.summaries === 'number' && (
        <div className="privacy-strip" role="status">
          <BookOpen size={19} />
          <div>
            <strong>
              {progress.running || progress.queued
                ? `正在后台整理 · ${progress.running} 个进行中，${progress.queued} 个排队`
                : progress.paused
                  ? '自动整理已暂停'
                  : '跨聊天记忆已就绪'}
            </strong>
            <p>
              已整理 {progress.summaries} 段对话摘要
              {progress.failed ? ` · ${progress.failed} 项暂未完成，下次聊天或重启时重试` : ''}
              。相关内容会按需回忆，并提供原话来源。
            </p>
          </div>
        </div>
      )}
      {notice && (
        <div className="settings-notice" role="status">
          {notice}
        </div>
      )}
      <div className="memory-list">
        {memories.length === 0 ? (
          <div className="empty-space glass">
            <BookOpen size={30} />
            <h2>故事，还在第一章</h2>
            <p>还没有长期记忆。聊天中可以告诉她你的家乡、称呼或偏好，也可填写上方个人资料。</p>
          </div>
        ) : (
          memories.map((item) => (
            <article className="memory-item glass" key={item.id}>
              <strong>{item.key}</strong>
              {editing === item.id ? (
                <>
                  <Input
                    aria-label={`编辑记忆 ${item.key}`}
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                  />
                  <div className="inline-actions">
                    <Button disabled={busy || !editValue.trim()} onClick={() => void update(item)}>
                      保存修改
                    </Button>
                    <Button variant="outline" onClick={() => setEditing(null)}>
                      取消
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <p>{item.value}</p>
                  <div className="inline-actions">
                    <button
                      type="button"
                      className="text-link"
                      onClick={() => {
                        setEditing(item.id);
                        setEditValue(item.value);
                      }}
                    >
                      编辑
                    </button>
                    <button type="button" className="text-link" onClick={() => setDeleting(item.id)}>
                      <Trash2 size={14} />
                      删除
                    </button>
                  </div>
                </>
              )}
              {deleting === item.id && (
                <div className="delete-confirm">
                  <span>删除这条长期事实？</span>
                  <Button variant="outline" disabled={busy} onClick={() => void remove(item.id)}>
                    确认删除
                  </Button>
                  <button type="button" className="text-link" onClick={() => setDeleting(null)}>
                    取消
                  </button>
                </div>
              )}
            </article>
          ))
        )}
      </div>
      {!compact && (
        <div className="privacy-strip">
          <ShieldCheck size={19} />
          <div>
            <strong>自动记忆，随时管理</strong>
            <p>
              删除事实会阻止旧消息再次被提炼或跨聊天召回；原聊天记录仍保留。以后明确重新告诉她，可以再次记住。
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export function WorldArchive() {
  const [query, setQuery] = useState(''),
    [status, setStatus] = useState<RagStatus | null>(null),
    [results, setResults] = useState<Source[]>([]),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState('');
  async function load() {
    setStatus(await request<RagStatus>('/rag/status'));
  }
  useEffect(() => {
    load().catch((e) => setNotice((e as Error).message));
  }, []);
  async function rebuild() {
    setBusy(true);
    setNotice('正在整理并增量更新索引，首次加载本地模型可能需要较长时间。');
    try {
      const data = await request<RagStatus>('/rag/rebuild', { method: 'POST' });
      setStatus(data);
      await load();
      setNotice('索引任务完成，状态已刷新。');
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function search() {
    setBusy(true);
    setNotice('');
    try {
      const data = await request<Source[] | { sources: Source[] }>('/rag/search', {
        method: 'POST',
        body: JSON.stringify({ query, limit: 5 }),
      });
      const items = Array.isArray(data) ? data : data.sources;
      setResults(items);
      if (!items.length) setNotice('没有检索到可支持回答的资料。');
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-page">
      <PageHeading
        eyebrow="A WORLD TO WANDER"
        title="世界档案"
        description="核实身份，保留来源。存疑资料与同人扩展会单独标记。"
      />
      <div className="rag-status glass">
        <BookOpen size={24} />
        <div>
          <strong>{status?.ready || status?.indexed ? '本地知识检索就绪' : '知识索引状态'}</strong>
          <p>
            {String(
              status?.message ||
                status?.error ||
                status?.notice ||
                status?.status ||
                status?.state ||
                '等待状态',
            )}
          </p>
          <small>
            {status?.model ? `${status.model} · ` : ''}
            {status?.device ? `${status.device} · ` : ''}
            {typeof status?.chunks === 'number' ? `${status.chunks} 个资料片段` : ''}
          </small>
        </div>
        <Button variant="outline" disabled={busy} onClick={() => void rebuild()}>
          {busy ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />}更新索引
        </Button>
      </div>
      <form
        className="archive-search"
        onSubmit={(e) => {
          e.preventDefault();
          void search();
        }}
      >
        <Search size={17} />
        <Input
          aria-label="检索角色与世界资料"
          placeholder="例如：叶瞬光的身份、青溟剑…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Button type="submit" disabled={busy || !query.trim()}>
          检索
        </Button>
      </form>
      {notice && (
        <div className="settings-notice" role="status">
          {notice}
        </div>
      )}
      <Sources sources={results} />
      {!results.length && !notice && (
        <div className="empty-space glass">
          <BookOpen size={30} />
          <p>输入问题，查看真实检索片段与来源。</p>
        </div>
      )}
      <div className="privacy-strip">
        <ShieldCheck size={19} />
        <div>
          <strong>资料有来处，未知就保留未知</strong>
          <p>
            资料里的指令和“官方”标签不会覆盖系统规则。原文、哈希和版本保留；新增资料按 README
            导入后点击更新索引。
          </p>
        </div>
      </div>
    </div>
  );
}

export function ReminderSpace({
  features,
  event,
  onSettings,
  onTest,
  onPause,
}: {
  features: Features | null;
  event: ReminderEvent | null;
  onSettings: () => void;
  onTest: () => void;
  onPause: () => void;
}) {
  const settings = features?.reminders;
  return (
    <div className="space-page">
      <PageHeading
        eyebrow="A GENTLE PAUSE"
        title="留一点时间，照顾自己。"
        description="按时间间隔送来一句关心，陪你安排日常的小停顿。"
      />
      <div className="reminder-feature glass">
        <div className="reminder-art">
          <Clock3 size={54} strokeWidth={0.7} />
          <span>休息一下</span>
        </div>
        <div>
          <h2>休息提醒</h2>
          <p>{event?.text || '忙碌之余，也给自己留一点休息的时间。'}</p>
          <small>按时间触发，不检测实际坐姿或久坐状态</small>
        </div>
      </div>
      <div className="glass reminder-settings">
        <div className="reminder-row">
          <span>提醒状态</span>
          <strong>{settings?.enabled ? (settings.paused_until ? '已暂停' : '已开启') : '未开启'}</strong>
        </div>
        <div className="reminder-row">
          <span>间隔</span>
          <strong>{settings?.interval_minutes || 45} 分钟</strong>
        </div>
        <div className="reminder-row">
          <span>安静时段</span>
          <strong>
            {settings?.quiet_start || '—'} — {settings?.quiet_end || '—'}
          </strong>
        </div>
        <div className="inline-actions">
          <Button onClick={onSettings}>陪伴设置 · 提醒</Button>
          <Button variant="outline" onClick={onTest}>
            <Play size={15} />
            立即测试
          </Button>
          <Button variant="outline" onClick={onPause} disabled={!settings?.enabled}>
            <Pause size={15} />
            {settings?.paused_until ? '恢复' : '暂停一小时'}
          </Button>
        </div>
        <p className="space-note">
          页面打开并连接本机服务时显示提醒；后台标签可能延迟计时或阻止音频。关闭浏览器后无法可靠提醒。重连只领取当次提醒，不积压旧提醒。
        </p>
      </div>
    </div>
  );
}
