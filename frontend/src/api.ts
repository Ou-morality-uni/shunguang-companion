export interface ModelSettings {
  base_url: string; model: string; temperature: number; timeout: number;
  has_api_key: boolean; configured: boolean;
  provider?: string; protocol?: 'openai' | 'anthropic';
}
export interface Conversation { id: string; title: string; created_at: string; updated_at: string; }
export interface Source { id?: string; number?:number; title?: string; text?: string; snippet?:string; url?: string; source_url?: string; document_id?: string; verification_status?: string; spoiler?: string | boolean; version?: string; score?: number; }
export interface ToolEvent { id?:string; name?: string; tool?: string; status?: string; message?: string; result?: unknown; arguments?: unknown; }
export interface Message { id: string; role: 'user' | 'assistant'; content: string; status: string; created_at: string; sources?: Source[]; tools?: ToolEvent[]; }
export interface Memory { id: string; key: string; value: string; source_message_id?: string; created_at?: string; updated_at?: string; }
export interface Candidate extends Memory { evidence?: string; existing_value?: string; }
export interface Provider { id: string; name: string; base_url: string; protocol?: 'openai' | 'anthropic'; models?: string[]; voices?: Array<{id:string;name?:string}>; model?:string; voice?:string; reference_supported?: boolean; reference_audio?:boolean; notice?: string; }
export interface Features {
  tools: {weather_enabled:boolean; search_enabled:boolean; search_provider:string; has_api_key:boolean; timeout?:number};
  tts: {provider:string; base_url:string; model:string; voice:string; has_api_key:boolean; configured?:boolean; enabled?:boolean; auto_play?:boolean; muted?:boolean; speed?:number; timeout?:number; reference_id?:string; reference_path?:string; reference_sha256?:string; reference_text?:string; reference_start?:number; reference_end?:number; allow_reference_upload?:boolean; reference_supported?:boolean; external_reference_enabled?:boolean;use_model_key?:boolean;style?:string;capabilities?:{reference_audio:boolean;voice_discovery:boolean;reference_upload_local:boolean}};
  reminders: {enabled:boolean; interval_minutes:number; quiet_start:string; quiet_end:string; timezone:string; voice:boolean; paused_until:string|null};
}
export interface ReminderEvent {id:string; text:string; voice:boolean; created_at:string}
export interface VoiceReference {id:string; name?:string; path?:string; url?:string; audio_url?:string; duration?:number; transcript?:string; text?:string; original_url?:string; notice?:string; }
export interface InspectedVoiceReference {id:string;name:string;path:string;format:string;bytes:number;sha256:string;duration:number;url?:string;notice?:string}
export interface RagStatus {ready?:boolean; indexed?:boolean; state?:string; status?:string; documents?:number | unknown[]; chunks?:number; points?:number; model?:string; device?:string; error?:string; message?:string; notice?:string; [key:string]:unknown}

export const avatarUrl = '/api/resources/character/avatar.png';
export function safeSourceUrl(value?: string) {
  if (!value) return undefined;
  try { const url=new URL(value,window.location.origin); return url.protocol==='https:' || url.protocol==='http:' ? url.href : undefined; } catch {return undefined;}
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
  if (!response.ok) {
    if(response.status===401) window.dispatchEvent(new Event('shunguang-auth-required'));
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}）`);
  }
  return response.json();
}

export async function streamChat(
  conversation_id: string, content: string, signal: AbortSignal,
  onEvent: (event: string, data: Record<string, unknown>) => void,
) {
  const response = await fetch('/api/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id, content }), signal,
  });
  if (!response.ok) {
    if(response.status===401) window.dispatchEvent(new Event('shunguang-auth-required'));
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : '对话请求失败');
  }
  if (!response.body) throw new Error('浏览器无法读取流式回复');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let completed = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary: number;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const kind = frame.split('\n').find(line => line.startsWith('event: '))?.slice(7);
        const payload = frame.split('\n').filter(line => line.startsWith('data: ')).map(line => line.slice(6)).join('\n');
        if (kind && payload) {
          if (kind === 'done' || kind === 'error') completed = true;
          onEvent(kind, JSON.parse(payload));
        }
      }
      if (done) break;
    }
    if (!completed) throw new Error('连接提前结束，请刷新查看已保存的内容。');
  } finally {
    reader.releaseLock();
  }
}
