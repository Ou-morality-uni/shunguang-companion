import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, MotionConfig } from 'motion/react';
import {
  ArrowUpRight,
  AudioLines,
  Bell,
  ChevronRight,
  CircleHelp,
  Compass,
  Cpu,
  Flower2,
  Heart,
  LoaderCircle,
  Menu,
  MessageSquare,
  Plus,
  Settings2,
  ShieldCheck,
  Wrench,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { request, type Features, type Memory, type ModelSettings, type ReminderEvent } from './api';
import { Atmosphere } from './Atmosphere';
import { ChatThread } from './ChatThread';
import { MemorySpace, WorldArchive, ReminderSpace, VoiceConsole, type Page, type Panel } from './Spaces';
import { CompanionSettings } from './CompanionSettings';
import { AudioContextValue, useAudioQueue } from './useAudioQueue';
import { useConversation } from './useConversation';
import { ConversationHistory } from './ConversationHistory';
import { ResourceImage } from './ResourceImage';

const pages = [
  { key: 'chat', label: '陪伴对话', icon: MessageSquare },
  { key: 'memory', label: '记忆空间', icon: Heart },
  { key: 'world', label: '世界档案', icon: Compass },
  { key: 'reminders', label: '温柔提醒', icon: Bell },
] as const;
function preference(key: string, defaultValue: boolean) {
  try {
    return localStorage.getItem(key) === null ? defaultValue : localStorage.getItem(key) === 'on';
  } catch {
    return defaultValue;
  }
}
export default function App() {
  const [settings, setSettings] = useState<ModelSettings | null>(null),
    [features, setFeatures] = useState<Features | null>(null),
    [memoryCount, setMemoryCount] = useState(0);
  const [panel, setPanel] = useState<Panel>(null),
    [page, setPage] = useState<Page>('chat'),
    [loading, setLoading] = useState(true),
    [mobileNav, setMobileNav] = useState(false);
  const [effects, setEffects] = useState(() => preference('shunguang-ui-effects', true)),
    [reduceMotion, setReduceMotion] = useState(() => preference('shunguang-ui-reduce-motion', false)),
    [background, setBackground] = useState(document.hidden),
    [systemReduce, setSystemReduce] = useState(matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [authRequired, setAuthRequired] = useState(false),
    [password, setPassword] = useState(''),
    [authBusy, setAuthBusy] = useState(false),
    [authError, setAuthError] = useState(''),
    [reminder, setReminder] = useState<ReminderEvent | null>(null);
  const [smallScreen, setSmallScreen] = useState(matchMedia('(max-width:700px)').matches);
  useEffect(() => {
    const media = matchMedia('(max-width:700px)');
    const change = () => setSmallScreen(media.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  const seenReminders = useRef(new Set<string>()),
    audio = useAudioQueue(features?.tts),
    audioRef = useRef(audio),
    featuresRef = useRef(features);
  audioRef.current = audio;
  featuresRef.current = features;
  const chat = useConversation(
    (message) => {
      audioRef.current.finishReply(message.content);
      void refreshMemory();
    },
    {
      start: () => audioRef.current.beginReply(),
      delta: (text) => audioRef.current.appendReply(text),
      cancel: () => audioRef.current.stop(),
    },
  );
  const {
    conversations,
    active,
    messages,
    busy,
    historyLoading,
    error,
    setError,
    partial,
    currentTools,
    currentSources,
    abortRef,
    stopReply,
  } = chat;
  async function refreshMemory() {
    try {
      const data = await request<Memory[]>('/memories');
      setMemoryCount(data.length);
    } catch {
      /* Main connection errors are shown independently. */
    }
  }
  async function refresh() {
    const [config] = await Promise.all([request<ModelSettings>('/settings'), chat.refreshConversations()]);
    setSettings(config);
    const optional = await Promise.allSettled([
      request<Features>('/features').then(setFeatures),
      refreshMemory(),
    ]);
    if (optional[0].status === 'rejected') setError('部分功能配置无法读取，请检查本机服务。');
  }
  useEffect(() => {
    let live = true;
    async function start() {
      try {
        const status = await request<{ required: boolean; authenticated: boolean }>('/auth/status');
        if (!live) return;
        setAuthRequired(status.required && !status.authenticated);
        if (!status.required || status.authenticated) await refresh();
      } catch {
        if (live) setError('暂时连接不上本机服务，请确认后端已启动。');
      } finally {
        if (live) setLoading(false);
      }
    }
    void start();
    const auth = () => {
      setAuthRequired(true);
      abortRef.current?.abort();
      audioRef.current.stop();
    };
    window.addEventListener('shunguang-auth-required', auth);
    return () => {
      live = false;
      abortRef.current?.abort();
      window.removeEventListener('shunguang-auth-required', auth);
    };
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem('shunguang-ui-effects', effects ? 'on' : 'off');
      localStorage.setItem('shunguang-ui-reduce-motion', reduceMotion ? 'on' : 'off');
    } catch {
      /* Private mode remains usable. */
    }
  }, [effects, reduceMotion]);
  useEffect(() => {
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    const change = () => setSystemReduce(media.matches),
      visibility = () => setBackground(document.hidden);
    media.addEventListener('change', change);
    document.addEventListener('visibilitychange', visibility);
    return () => {
      media.removeEventListener('change', change);
      document.removeEventListener('visibilitychange', visibility);
    };
  }, []);
  useEffect(() => {
    const viewport = window.visualViewport;
    const resize = () => {
      if (matchMedia('(max-width:700px)').matches && viewport)
        document.documentElement.style.setProperty('--app-height', `${viewport.height}px`);
      else document.documentElement.style.removeProperty('--app-height');
    };
    resize();
    viewport?.addEventListener('resize', resize);
    window.addEventListener('resize', resize);
    return () => {
      viewport?.removeEventListener('resize', resize);
      window.removeEventListener('resize', resize);
      document.documentElement.style.removeProperty('--app-height');
    };
  }, []);
  function acceptReminder(event: ReminderEvent | null) {
    if (!event || seenReminders.current.has(event.id)) return;
    seenReminders.current.add(event.id);
    if (seenReminders.current.size > 200)
      seenReminders.current.delete(seenReminders.current.values().next().value!);
    setReminder(event);
    if (event.voice) audioRef.current.enqueue(event.text, '关怀提醒');
  }
  useEffect(() => {
    if (loading || authRequired) return;
    let live = true,
      running = false;
    const poll = async () => {
      if (running) return;
      running = true;
      try {
        const data = await request<{ event: ReminderEvent | null }>('/reminders/poll');
        if (live) acceptReminder(data.event);
      } catch {
        /* Poll failure does not interrupt chat. */
      } finally {
        running = false;
      }
    };
    void poll();
    const timer = window.setInterval(poll, 10000);
    const visible = () => {
      if (!document.hidden) void poll();
    };
    document.addEventListener('visibilitychange', visible);
    return () => {
      live = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [loading, authRequired]);
  async function testReminder() {
    try {
      const data = await request<{ event: ReminderEvent }>('/reminders/test', { method: 'POST' });
      acceptReminder(data.event);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function pauseReminder() {
    if (!features) return;
    try {
      setFeatures(
        await request<Features>('/features', {
          method: 'PATCH',
          body: JSON.stringify({
            reminders: {
              paused_until: features.reminders.paused_until
                ? null
                : new Date(Date.now() + 3600000).toISOString(),
            },
          }),
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function openPanel(next: Panel) {
    setPanel(next);
    setMobileNav(false);
  }
  function navigate(next: Page) {
    setPage(next);
    setMobileNav(false);
  }
  async function login() {
    setAuthBusy(true);
    setAuthError('');
    try {
      await request('/auth/login', { method: 'POST', body: JSON.stringify({ password }) });
      setPassword('');
      setAuthRequired(false);
      setLoading(true);
      await refresh();
      setError('');
    } catch (e) {
      setAuthError((e as Error).message);
    } finally {
      setAuthBusy(false);
      setLoading(false);
    }
  }
  function newConversation() {
    chat.selectConversation(null);
    navigate('chat');
  }
  async function send(text: string): Promise<boolean> {
    if (loading) return false;
    if (!settings?.configured) {
      openPanel('model');
      return false;
    }
    return chat.send(text);
  }
  const title =
    page === 'chat'
      ? (conversations.find((item) => item.id === active)?.title ?? '新的相遇')
      : pages.find((item) => item.key === page)?.label;
  const agentState = busy
    ? currentTools.at(-1)?.status === 'running'
      ? '正在调用工具'
      : partial
        ? '正在回应'
        : '正在思考'
    : error
      ? '需要关注'
      : settings?.configured
        ? '等待你的消息'
        : '等待模型连接';
  const animate = effects && !reduceMotion && !systemReduce && !background;
  return (
    <AudioContextValue.Provider value={audio}>
      <MotionConfig reducedMotion={animate ? 'user' : 'always'}>
        <div className={`app-shell ${animate ? '' : 'effects-off'}`}>
          <Atmosphere enabled={animate} />
          {mobileNav && (
            <button className="nav-overlay" aria-label="关闭导航" onClick={() => setMobileNav(false)} />
          )}
          <aside
            id="primary-navigation"
            aria-hidden={smallScreen && !mobileNav ? true : undefined}
            inert={smallScreen && !mobileNav ? true : undefined}
            className={`sidebar ${mobileNav ? 'is-open' : ''}`}
          >
            <a className="brand" href="/" aria-label="瞬光伴行首页">
              <span className="brand-mark">
                <Flower2 strokeWidth={1.1} />
              </span>
              <span>
                瞬光伴行<small>SHUNGUANG COMPANION</small>
              </span>
            </a>
            <div className="sidebar-theme">
              <span className="subtle-dot" />
              暖霞拾光<span>THE WARM DAWN</span>
            </div>
            <Button className="new-chat" onClick={newConversation} disabled={busy || loading}>
              <Plus size={17} />
              开启新的对话
            </Button>
            <div className="nav-section-label">
              相伴的日常<span>01 — 04</span>
            </div>
            <nav aria-label="功能导航">
              {pages.map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  className={`nav-item ${page === key ? 'selected' : ''}`}
                  onClick={() => navigate(key)}
                  aria-current={page === key ? 'page' : undefined}
                >
                  <Icon size={18} strokeWidth={1.6} />
                  <span>{label}</span>
                  {key === 'chat' ? (
                    <span className="nav-count">{conversations.length}</span>
                  ) : (
                    <ChevronRight className="nav-arrow" size={13} />
                  )}
                </button>
              ))}
            </nav>
            <div className="history-heading">
              最近对话<span>本机保存</span>
            </div>
            <ConversationHistory
              conversations={conversations}
              active={active}
              disabled={busy || historyLoading}
              onSelect={(id) => {
                chat.selectConversation(id);
                navigate('chat');
              }}
              onDelete={chat.deleteConversation}
            />
            <div className="sidebar-bottom">
              <button className="nav-item" onClick={() => openPanel('model')}>
                <Settings2 size={18} />
                陪伴设置
                <ChevronRight className="nav-arrow" size={14} />
              </button>
              <div className="local-note">
                <ShieldCheck size={14} />
                <span>记录保存在运行服务的电脑</span>
              </div>
              <div className="version">
                <span className="version-dot" />
                瞬光伴行 WEB<span>v0.1.5</span>
              </div>
            </div>
          </aside>
          <main className="workspace">
            <header className="topbar">
              <div className="topbar-left">
                <button
                  className="icon-button mobile-menu"
                  onClick={() => setMobileNav(true)}
                  aria-label="展开导航"
                  aria-expanded={mobileNav}
                  aria-controls="primary-navigation"
                >
                  <Menu size={20} />
                </button>
                <span className="breadcrumb">暖霞拾光</span>
                <ChevronRight size={13} />
                <strong>{title}</strong>
              </div>
              <div className="topbar-right">
                <span className="quiet-caption">一隅暖霞 · 一路相伴</span>
                <button
                  className={`connection ${settings?.configured ? 'configured' : ''}`}
                  onClick={() => openPanel('model')}
                >
                  <span />
                  {loading ? '连接本机服务中' : settings?.configured ? '模型已配置' : '连接模型'}
                  <ChevronRight size={12} />
                </button>
              </div>
            </header>
            <div className="content-columns">
              <section className="chat-column" aria-label="主内容区域">
                {error && (
                  <div role="alert" className="error-banner">
                    <CircleHelp size={17} />
                    <span>{error}</span>
                    <button className="icon-button" aria-label="关闭提示" onClick={() => setError('')}>
                      <X size={15} />
                    </button>
                  </div>
                )}
                {reminder && (
                  <div className="reminder-banner" role="status">
                    <Bell size={17} />
                    <span>{reminder.text}</span>
                    <button
                      className="icon-button"
                      onClick={() => audio.enqueue(reminder.text, '关怀提醒')}
                      aria-label="播放提醒"
                    >
                      <AudioLines size={16} />
                    </button>
                    <button className="icon-button" onClick={() => setReminder(null)} aria-label="关闭提醒">
                      <X size={16} />
                    </button>
                  </div>
                )}
                <div className={`page-container ${page === 'chat' ? 'chat-page' : ''}`}>
                  <AnimatePresence mode="wait">
                    <motion.div
                      key={page}
                      className="page-transition"
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -6 }}
                      transition={{ duration: 0.2 }}
                    >
                      {page === 'chat' ? (
                        <ChatThread
                          key={active ?? 'new'}
                          messages={messages}
                          partial={partial}
                          tools={currentTools}
                          sources={currentSources}
                          busy={busy}
                          loading={loading || historyLoading}
                          configured={!!settings?.configured}
                          onSend={send}
                          onStop={() => void stopReply()}
                          onSettings={() => openPanel('model')}
                          onVoice={() => openPanel('voice')}
                          onTools={() => openPanel('tools')}
                        />
                      ) : page === 'memory' ? (
                        <MemorySpace
                          conversations={conversations}
                          active={active}
                          onChanged={() => void refreshMemory()}
                        />
                      ) : page === 'world' ? (
                        <WorldArchive />
                      ) : (
                        <ReminderSpace
                          features={features}
                          event={reminder}
                          onSettings={() => openPanel('reminders')}
                          onTest={() => void testReminder()}
                          onPause={() => void pauseReminder()}
                        />
                      )}
                    </motion.div>
                  </AnimatePresence>
                </div>
              </section>
              <aside className="companion-column" aria-label="陪伴信息">
                <div className="profile-card glass">
                  <div className="profile-art">
                    <ResourceImage
                      className="character-portrait"
                      src="/api/resources/assets/ye-shunguang/warm-dawn-full-body.webp"
                      alt="叶瞬光暖霞立绘"
                      label
                    />
                    <span className="art-seal">
                      暖<br />霞
                    </span>
                  </div>
                  <div className="profile-info">
                    <div className="profile-eyebrow">YOUR EVERYDAY COMPANION</div>
                    <h2>
                      叶瞬光<span>暖霞拾光</span>
                    </h2>
                    <p>把故事里的相遇，延续到日常。</p>
                    <div className="profile-status">
                      <span className="subtle-dot" />
                      你的日常陪伴
                    </div>
                  </div>
                </div>
                <div className="agent-card glass">
                  <div className="detail-heading">
                    <Cpu size={15} />
                    <h3>Agent 状态</h3>
                    <span className={`agent-dot ${busy ? 'active' : ''}`} />
                  </div>
                  <div className="agent-state" role="status">
                    {busy ? <LoaderCircle className="spin" size={15} /> : <span className="subtle-dot" />}
                    {agentState}
                  </div>
                  <div className="agent-steps">
                    <span className={busy ? 'step-active' : ''}>接收</span>
                    <i />
                    <span className={busy && !partial ? 'step-active' : ''}>思考</span>
                    <i />
                    <span className={busy && partial ? 'step-active' : ''}>回应</span>
                  </div>
                  <button className="text-link" onClick={() => openPanel('tools')}>
                    <Wrench size={12} />
                    工具设置
                    <ArrowUpRight size={12} />
                  </button>
                </div>
                <div className="detail-card voice-card glass">
                  <div className="detail-heading">
                    <AudioLines size={15} />
                    <h3>声音的温度</h3>
                    <span>{features?.tts.enabled ? '已开启' : '未开启'}</span>
                  </div>
                  <VoiceConsole compact />
                  <button className="text-link" onClick={() => openPanel('voice')}>
                    声音与播放设置
                    <ArrowUpRight size={12} />
                  </button>
                </div>
                <div className="detail-card memory-card glass">
                  <div className="detail-heading">
                    <Heart size={15} />
                    <h3>记忆拾光</h3>
                    <span>{memoryCount} 条</span>
                  </div>
                  <div className="memory-card-content">
                    <p>{memoryCount ? '把你说过的小事，放在心上。' : '从空白开始，慢慢认识你。'}</p>
                    <ResourceImage
                      src="/api/resources/character/stickers/10-red-pat.png"
                      alt="叶瞬光摸头表情"
                    />
                  </div>
                  <button className="text-link" onClick={() => navigate('memory')}>
                    走进记忆空间
                    <ArrowUpRight size={12} />
                  </button>
                </div>
                <button className="reminder-mini" onClick={() => navigate('reminders')}>
                  <span className="reminder-mini-icon">
                    <Bell size={17} />
                  </span>
                  <span>
                    也记得，照顾好自己
                    <small>
                      {features?.reminders.enabled
                        ? `每 ${features.reminders.interval_minutes} 分钟 · ${features.reminders.paused_until ? '已暂停' : '已开启'}`
                        : '温柔提醒 · 未开启'}
                    </small>
                  </span>
                  <ChevronRight size={14} />
                </button>
                <div className="margin-note">
                  ✦ <span>有时聊聊，就很好。</span>
                </div>
              </aside>
            </div>
          </main>
          <CompanionSettings
            panel={panel}
            setPanel={setPanel}
            settings={settings}
            features={features}
            effects={effects}
            setEffects={setEffects}
            reduceMotion={reduceMotion}
            setReduceMotion={setReduceMotion}
            onModelSaved={setSettings}
            onFeaturesSaved={setFeatures}
            conversations={conversations}
            active={active}
            onMemoryChanged={() => void refreshMemory()}
            onTestReminder={() => void testReminder()}
          />
          {authRequired && (
            <div className="auth-overlay">
              <form
                className="auth-card glass"
                onSubmit={(e) => {
                  e.preventDefault();
                  void login();
                }}
              >
                <ShieldCheck size={36} />
                <h1>连接你的陪伴空间</h1>
                <p>局域网模式需要访问口令。口令由运行服务的电脑提供，仅用于本机会话验证。</p>
                <label className="field">
                  访问口令
                  <Input
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    autoFocus
                  />
                </label>
                {authError && (
                  <p role="alert" className="settings-notice">
                    {authError}
                  </p>
                )}
                <Button disabled={authBusy} type="submit">
                  {authBusy && <LoaderCircle className="spin" size={15} />}进入陪伴空间
                </Button>
              </form>
            </div>
          )}
        </div>
      </MotionConfig>
    </AudioContextValue.Provider>
  );
}
