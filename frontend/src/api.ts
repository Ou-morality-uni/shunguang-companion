import type { components } from './generated/api-schema';
import { SseDecoder } from './sse';
type Schemas = components['schemas'];
type OptionalFields<T> = { [K in keyof T]?: Exclude<T[K], null> };
export type ModelSettings = Schemas['SettingsOut'];
export type Conversation = Schemas['ConversationOut'];
export type Source = OptionalFields<Schemas['SourceOut']>;
export type ToolEvent = OptionalFields<Schemas['ToolEventOut']>;
export type Message = Omit<Schemas['MessageOut'], 'conversation_id' | 'status' | 'sources' | 'tools'> & {
  conversation_id?: string;
  status: Schemas['MessageOut']['status'] | 'running';
  sources?: Source[];
  tools?: ToolEvent[];
};
export interface Memory {
  id: string;
  key: string;
  value: string;
  source_message_id?: string;
  created_at?: string;
  updated_at?: string;
}
export interface Candidate extends Memory {
  evidence?: string;
  existing_value?: string;
}
export interface Provider {
  id: string;
  name: string;
  base_url: string;
  protocol?: 'openai' | 'anthropic';
  models?: string[];
  voices?: Array<{ id: string; name?: string }>;
  model?: string;
  voice?: string;
  reference_supported?: boolean;
  reference_audio?: boolean;
  notice?: string;
}
export interface Features {
  tools: {
    weather_enabled: boolean;
    search_enabled: boolean;
    search_provider: string;
    has_api_key: boolean;
    timeout?: number;
  };
  tts: {
    provider: string;
    base_url: string;
    model: string;
    voice: string;
    resource_id?: string;
    has_api_key: boolean;
    configured?: boolean;
    enabled?: boolean;
    auto_play?: boolean;
    muted?: boolean;
    speed?: number;
    timeout?: number;
    reference_id?: string;
    reference_path?: string;
    reference_sha256?: string;
    reference_text?: string;
    reference_start?: number;
    reference_end?: number;
    allow_reference_upload?: boolean;
    reference_supported?: boolean;
    external_reference_enabled?: boolean;
    use_model_key?: boolean;
    style?: string;
    capabilities?: {
      reference_audio: boolean;
      voice_discovery: boolean;
      reference_upload_local: boolean;
      persistent_voice?: boolean;
      streaming_audio?: boolean;
      voice_id_generation?: boolean;
    };
  };
  reminders: {
    enabled: boolean;
    interval_minutes: number;
    quiet_start: string;
    quiet_end: string;
    timezone: string;
    voice: boolean;
    paused_until: string | null;
  };
}
export interface ReminderEvent {
  id: string;
  text: string;
  voice: boolean;
  created_at: string;
}
export interface VoiceReference {
  id: string;
  name?: string;
  path?: string;
  url?: string;
  audio_url?: string;
  duration?: number;
  transcript?: string;
  text?: string;
  original_url?: string;
  notice?: string;
}
export interface InspectedVoiceReference {
  id: string;
  name: string;
  path: string;
  format: string;
  bytes: number;
  sha256: string;
  duration: number;
  url?: string;
  notice?: string;
}
export interface RagStatus {
  ready?: boolean;
  indexed?: boolean;
  state?: string;
  status?: string;
  documents?: number | unknown[];
  chunks?: number;
  points?: number;
  model?: string;
  device?: string;
  error?: string;
  message?: string;
  notice?: string;
  [key: string]: unknown;
}

export const avatarUrl = '/api/resources/character/avatar.png';
export function safeSourceUrl(value?: string) {
  if (!value) return undefined;
  try {
    const url = new URL(value, window.location.origin);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('shunguang-auth-required'));
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}）`);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export async function streamChat(
  conversation_id: string | null,
  content: string,
  signal: AbortSignal,
  onEvent: (event: string, data: Record<string, unknown>) => void,
) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id, content }),
    signal,
  });
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('shunguang-auth-required'));
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : '对话请求失败');
  }
  if (!response.body) throw new Error('浏览器无法读取流式回复');
  const reader = response.body.getReader();
  let completed = false;
  const decoder = new SseDecoder((kind, data) => {
    if (kind === 'done' || kind === 'error') completed = true;
    onEvent(kind, data);
  });
  try {
    while (true) {
      const { done, value } = await reader.read();
      decoder.push(value, done);
      if (done) break;
    }
    if (!completed) throw new Error('连接提前结束，请刷新查看已保存的内容。');
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
