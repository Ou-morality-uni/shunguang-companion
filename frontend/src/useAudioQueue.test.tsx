import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useAudioQueue } from './useAudioQueue';
import { request, type Features } from './api';
import { liveSpeech, streamSpeech } from './speechStream';

vi.mock('./api', () => ({ request: vi.fn() }));
vi.mock('./speechStream', async (original) => ({
  ...(await original<typeof import('./speechStream')>()),
  streamSpeech: vi.fn(),
  liveSpeech: vi.fn(),
}));
const settings: Features['tts'] = {
  provider: 'aliyun',
  base_url: 'https://dashscope.aliyuncs.com',
  model: 'qwen3-tts-vc-realtime-2026-01-15',
  voice: 'cloud-voice',
  enabled: true,
  auto_play: true,
  external_reference_enabled: true,
  reference_path: 'test.mp3',
  has_api_key: true,
};
let played: string[];
let nodes: { stop: ReturnType<typeof vi.fn>; start: ReturnType<typeof vi.fn> }[];
beforeEach(() => {
  vi.clearAllMocks();
  played = [];
  nodes = [];
  const graphNode = () => ({ connect: vi.fn(), disconnect: vi.fn(), gain: { value: 1 } });
  class Context {
    state = 'running';
    currentTime = 0;
    destination = {};
    createAnalyser = graphNode;
    createGain = graphNode;
    createMediaElementSource = graphNode;
    resume = vi.fn().mockResolvedValue(undefined);
    close = vi.fn().mockResolvedValue(undefined);
    createBuffer = (_channels: number, length: number, rate: number) => ({
      duration: length / rate,
      getChannelData: () => new Float32Array(length),
    });
    createBufferSource = () => {
      const node = {
        ...graphNode(),
        playbackRate: { value: 1 },
        start: vi.fn(),
        stop: vi.fn(),
        onended: null,
      };
      nodes.push(node);
      return node;
    };
  }
  vi.stubGlobal('AudioContext', Context);
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (this: HTMLMediaElement) {
    played.push(this.src);
    return Promise.resolve();
  });
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function pendingRequests() {
  const pending: { text: string; signal: AbortSignal; resolve: (value: { audio_url: string }) => void }[] =
    [];
  vi.mocked(request).mockImplementation(
    (_url, options) =>
      new Promise((resolve) => {
        pending.push({ text: JSON.parse(String(options?.body)).text, signal: options!.signal!, resolve });
      }),
  );
  return pending;
}

it('filters manual and whole reply speech while retaining displayed text unchanged', async () => {
  const pending = pendingRequests();
  const { result } = renderHook(() => useAudioQueue(settings));
  const text = '说明。\n```json\n{"private_code": true}\n```\n结果。';
  act(() => {
    result.current.beginReply();
    result.current.appendReply(text);
    result.current.finishReply(text);
  });
  await waitFor(() => expect(pending).toHaveLength(1));
  expect(pending[0].text).toContain('结果。');
  expect(pending[0].text).not.toContain('private_code');
  act(() => result.current.stop());
  await act(async () => pending[0].resolve({ audio_url: '/api/tts/audio/stale.wav' }));
  act(() => result.current.enqueue('```\nonly boxed text\n```'));
  expect(pending).toHaveLength(1);
});

it('keeps task cues independent of reply autoplay and suppresses stale or muted work speech', async () => {
  const pending = pendingRequests();
  const { result } = renderHook(() => useAudioQueue({ ...settings, auto_play: false, work_prompts: true }));
  const event = {
    task_id: 't1',
    kind: 'start',
    text: '我先看看这份资料。',
    created_at: new Date().toISOString(),
  };
  act(() => result.current.enqueueWork({ ...event, created_at: new Date(Date.now() - 60000).toISOString() }));
  expect(pending).toHaveLength(0);
  act(() => result.current.enqueueWork(event));
  await waitFor(() => expect(pending).toHaveLength(1));
  act(() => result.current.cancelWork('t1'));
  expect(pending[0].signal.aborted).toBe(true);
  await act(async () => pending[0].resolve({ audio_url: '/api/tts/audio/cancelled.wav' }));
  expect(played).toHaveLength(0);
  act(() => result.current.toggleMute());
  act(() => result.current.enqueueWork(event));
  expect(pending).toHaveLength(1);
});

it('withholds code fence prefixes before flushing text to a live TTS socket', async () => {
  vi.useFakeTimers();
  const push = vi.fn();
  vi.mocked(liveSpeech).mockReturnValue({ push, finish: vi.fn(), promise: new Promise(() => {}) });
  const { result } = renderHook(() => useAudioQueue({ ...settings, model: 'qwen-audio-3.1-tts-flash' }));
  act(() => {
    result.current.beginReply();
    result.current.appendReply('先说说明。\n`');
  });
  await act(async () => vi.advanceTimersByTimeAsync(600));
  act(() => result.current.appendReply('``python\nprivate_code()\n``'));
  await act(async () => vi.advanceTimersByTimeAsync(600));
  act(() => {
    result.current.appendReply('`\n后面的说明。');
    result.current.finishReply('先说说明。\n```python\nprivate_code()\n```\n后面的说明。');
  });
  expect(push.mock.calls.map((call) => call[0]).join('')).toContain('后面的说明。');
  expect(push.mock.calls.map((call) => call[0]).join('')).not.toMatch(/private_code|python|`/);
  act(() => result.current.stop());
});

it('submits each Aliyun reply whole and plays queued replies in order', async () => {
  const pending = pendingRequests();
  const { result } = renderHook(() => useAudioQueue(settings));
  act(() => {
    result.current.enqueue('第一条回复。还有下一句。');
    result.current.enqueue('第二条回复。');
  });
  expect(pending.map((item) => item.text)).toEqual(['第一条回复。还有下一句。', '第二条回复。']);
  await act(async () => pending[1].resolve({ audio_url: '/api/tts/audio/second.wav' }));
  expect(played).toEqual([]);
  await act(async () => pending[0].resolve({ audio_url: '/api/tts/audio/first.wav' }));
  expect(played[0]).toContain('first.wav');
  await act(async () => document.querySelector('audio')!.dispatchEvent(new Event('ended')));
  expect(played[1]).toContain('second.wav');
  act(() => result.current.stop());
});

it('waits for the complete Aliyun reply, ignores punctuation and timers, and submits the final record once', async () => {
  vi.useFakeTimers();
  const pending = pendingRequests();
  const { result } = renderHook(() => useAudioQueue(settings));
  act(() => {
    result.current.beginReply();
    result.current.appendReply('第一句。还没结束');
  });
  expect(pending).toHaveLength(0);
  await act(async () => vi.advanceTimersByTimeAsync(5000));
  expect(pending).toHaveLength(0);
  act(() => {
    result.current.appendReply('。第二段\n' + '长句'.repeat(120));
    result.current.finishReply('第一句。还没结束。第二段\n最后保存的完整回答。');
    result.current.finishReply('第一句。还没结束。第二段\n最后保存的完整回答。');
  });
  expect(pending.map((item) => item.text)).toEqual(['第一句。还没结束。第二段\n最后保存的完整回答。']);
  act(() => result.current.stop());
  await act(async () => pending.forEach((item) => item.resolve({ audio_url: '/api/tts/audio/old.wav' })));
});

it('aborts every old request and rejects late audio after a new turn', async () => {
  const pending = pendingRequests();
  const { result } = renderHook(() => useAudioQueue(settings));
  act(() => {
    result.current.beginReply();
    result.current.appendReply('旧句一。旧句二。');
    result.current.finishReply('旧句一。旧句二。');
  });
  act(() => {
    result.current.beginReply();
    result.current.appendReply('新句。');
    result.current.finishReply('新句。');
  });
  expect(pending[0].signal.aborted).toBe(true);
  await act(async () => pending[0].resolve({ audio_url: '/api/tts/audio/old.wav' }));
  await waitFor(() => expect(pending).toHaveLength(2));
  await act(async () => pending[1].resolve({ audio_url: '/api/tts/audio/new.wav' }));
  expect(played).toHaveLength(1);
  expect(played[0]).toContain('new.wav');
  act(() => result.current.stop());
});

it('plays PCM before synthesis completes and stops scheduled audio immediately', async () => {
  let emit: (bytes: Uint8Array) => void = () => {};
  let finish: (url: string) => void = () => {};
  let signal: AbortSignal;
  vi.mocked(streamSpeech).mockImplementation((_text, currentSignal, onAudio) => {
    signal = currentSignal;
    emit = onAudio;
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  const persistent = {
    ...settings,
    provider: 'aliyun',
    voice: 'cloud-voice',
    capabilities: {
      reference_audio: false,
      reference_upload_local: true,
      voice_discovery: false,
      streaming_audio: true,
    },
  };
  const { result } = renderHook(() => useAudioQueue(persistent));
  act(() => {
    result.current.beginReply();
    result.current.appendReply('实时声音。第二句。');
  });
  expect(streamSpeech).not.toHaveBeenCalled();
  await act(async () => result.current.finishReply('实时声音。第二句。'));
  expect(streamSpeech).toHaveBeenCalledOnce();
  expect(vi.mocked(streamSpeech).mock.calls[0][0]).toBe('实时声音。第二句。');
  act(() => emit(new Uint8Array([1, 0, 2, 0])));
  expect(nodes[0].start).toHaveBeenCalledOnce();
  expect(result.current.playing).toBe(true);
  act(() => result.current.stop());
  expect(signal!.aborted).toBe(true);
  expect(nodes[0].stop).toHaveBeenCalledOnce();
  await act(async () => finish('/api/tts/audio/late.wav'));
  expect(played).toEqual([]);
});

it('does not synthesize a stopped Aliyun reply or a late completion after settings change', () => {
  const pending = pendingRequests();
  const { result, rerender } = renderHook(({ value }) => useAudioQueue(value), {
    initialProps: { value: settings },
  });
  act(() => {
    result.current.beginReply();
    result.current.appendReply('还没完成。');
    result.current.stop();
    result.current.finishReply('已经停止的完整回复。');
    result.current.beginReply();
    result.current.appendReply('旧音色下正在生成。');
  });
  rerender({ value: { ...settings, voice: 'new-cloud-voice' } });
  act(() => result.current.finishReply('配置已变化的完整回复。'));
  expect(pending).toHaveLength(0);
  expect(streamSpeech).not.toHaveBeenCalled();
});

it('plays final-only replies whole and replays the cached whole audio without another synthesis', async () => {
  const pending = pendingRequests();
  const { result } = renderHook(() => useAudioQueue(settings));
  act(() => {
    result.current.beginReply();
    result.current.finishReply('只有最终记录。也要完整朗读。');
  });
  expect(pending.map((item) => item.text)).toEqual(['只有最终记录。也要完整朗读。']);
  await act(async () => pending[0].resolve({ audio_url: '/api/tts/audio/whole.wav' }));
  await act(async () => document.querySelector('audio')!.dispatchEvent(new Event('ended')));
  await act(async () => result.current.replay());
  expect(pending).toHaveLength(1);
  expect(played).toHaveLength(2);
  expect(played[0]).toBe(played[1]);
  act(() => result.current.stop());
});

it('does not automatically speak an Aliyun reply when autoplay is disabled', () => {
  const pending = pendingRequests();
  const { result } = renderHook(() => useAudioQueue({ ...settings, auto_play: false }));
  act(() => {
    result.current.beginReply();
    result.current.appendReply('这一句只显示文字。');
    result.current.finishReply('这一句只显示文字。');
  });
  expect(pending).toHaveLength(0);
});

it('accepts exactly 3000 Unicode characters without cutting the reply into sentences', async () => {
  const pending = pendingRequests();
  const { result } = renderHook(() => useAudioQueue(settings));
  const text = '甲'.repeat(2998) + '😊😊';
  act(() => result.current.enqueue(text));
  expect(pending).toHaveLength(1);
  expect(pending[0].text).toBe(text);
  act(() => result.current.stop());
  await act(async () => pending[0].resolve({ audio_url: '/api/tts/audio/late.wav' }));
});

it('rejects oversized manual and automatic Aliyun replies before sending without truncating or splitting', () => {
  const pending = pendingRequests();
  const { result } = renderHook(() => useAudioQueue(settings));
  const text = '甲'.repeat(3001);
  act(() => result.current.enqueue(text));
  expect(result.current.error).toContain('3000');
  act(() => {
    result.current.beginReply();
    result.current.appendReply(text);
    result.current.finishReply(text);
  });
  expect(pending).toHaveLength(0);
  expect(streamSpeech).not.toHaveBeenCalled();
  expect(result.current.error).toContain('3000');
});

it('configuration changes abort work and invalidate replay', async () => {
  const pending = pendingRequests();
  const { result, rerender } = renderHook(({ value }) => useAudioQueue(value), {
    initialProps: { value: settings },
  });
  act(() => result.current.enqueue('旧配置。'));
  rerender({ value: { ...settings, reference_sha256: 'new-file' } });
  expect(pending[0].signal.aborted).toBe(true);
  await act(async () => pending[0].resolve({ audio_url: '/api/tts/audio/old.wav' }));
  act(() => result.current.replay());
  expect(result.current.error).toContain('当前配置');
  expect(played).toEqual([]);
});

it('batches short MiMo sentences and does not prefetch another billed request', async () => {
  vi.useFakeTimers();
  const pending = pendingRequests();
  const mimo = {
    ...settings,
    provider: 'mimo',
    base_url: 'https://api.xiaomimimo.com/v1',
    model: 'mimo-v2.5-tts-voiceclone',
    voice: '',
  };
  const { result } = renderHook(() => useAudioQueue(mimo));
  act(() => {
    result.current.beginReply();
    result.current.appendReply('第一句。第二句。');
  });
  expect(pending).toHaveLength(0);
  await act(async () => vi.advanceTimersByTimeAsync(2400));
  expect(pending.map((x) => x.text)).toEqual(['第一句。第二句。']);
  act(() => result.current.finishReply('第一句。第二句。'));
  expect(pending).toHaveLength(1);
  act(() => result.current.stop());
  expect(pending[0].signal.aborted).toBe(true);
  await act(async () => pending[0].resolve({ audio_url: '/api/tts/audio/old.wav' }));
});

it('appends Qwen-Audio text to one live task before completion, buffers audio, and cancels immediately', async () => {
  vi.useFakeTimers();
  let emit!: (bytes: Uint8Array) => void;
  let resolve!: (url: string) => void;
  let signal!: AbortSignal;
  const push = vi.fn(),
    finish = vi.fn();
  vi.mocked(liveSpeech).mockImplementation((s, audio) => {
    signal = s;
    emit = audio;
    return {
      push,
      finish,
      promise: new Promise((yes) => {
        resolve = yes;
      }),
    };
  });
  const { result } = renderHook(() => useAudioQueue({ ...settings, model: 'qwen-audio-3.1-tts-flash' }));
  act(() => {
    result.current.beginReply();
    result.current.appendReply('先听我说。');
  });
  expect(liveSpeech).not.toHaveBeenCalled();
  await act(async () => vi.advanceTimersByTimeAsync(600));
  expect(liveSpeech).toHaveBeenCalledOnce();
  expect(push).toHaveBeenCalledWith('先听我说。');
  await act(async () => emit(new Uint8Array(4800)));
  expect(nodes).toHaveLength(0);
  await act(async () => vi.advanceTimersByTimeAsync(350));
  expect(nodes[0].start).toHaveBeenCalledOnce();
  act(() => {
    result.current.appendReply('然后继续。');
    result.current.finishReply('先听我说。然后继续。');
  });
  expect(liveSpeech).toHaveBeenCalledOnce();
  expect(push.mock.calls.map((x) => x[0]).join('')).toBe('先听我说。然后继续。');
  expect(finish).toHaveBeenCalledOnce();
  act(() => result.current.stop());
  expect(signal.aborted).toBe(true);
  expect(nodes[0].stop).toHaveBeenCalledOnce();
  await act(async () => resolve('/api/tts/audio/late.wav'));
});

it('cancels a live task on settings changes and never resubmits partial text on failure', async () => {
  vi.useFakeTimers();
  let signal!: AbortSignal;
  let reject!: (error: Error) => void;
  vi.mocked(liveSpeech).mockImplementation((s) => {
    signal = s;
    return {
      push: vi.fn(),
      finish: vi.fn(),
      promise: new Promise((_yes, no) => {
        reject = no;
      }),
    };
  });
  const current = { ...settings, model: 'qwen-audio-3.1-tts-flash' };
  const { result, rerender } = renderHook(({ value }) => useAudioQueue(value), {
    initialProps: { value: current },
  });
  act(() => {
    result.current.beginReply();
    result.current.appendReply('正在朗读。');
  });
  await act(async () => vi.advanceTimersByTimeAsync(600));
  rerender({ value: { ...current, voice: 'changed' } });
  expect(signal.aborted).toBe(true);
  await act(async () => reject(new Error('disconnected')));
  act(() => result.current.finishReply('正在朗读。'));
  expect(liveSpeech).toHaveBeenCalledOnce();
  expect(request).not.toHaveBeenCalled();
});

it('replays only complete live audio from the cache without opening another cloud task', async () => {
  let emit!: (bytes: Uint8Array) => void;
  let resolve!: (url: string) => void;
  vi.mocked(liveSpeech).mockImplementation((_s, audio) => {
    emit = audio;
    return {
      push: vi.fn(),
      finish: vi.fn(),
      promise: new Promise((yes) => {
        resolve = yes;
      }),
    };
  });
  const { result } = renderHook(() => useAudioQueue({ ...settings, model: 'qwen-audio-3.1-tts-flash' }));
  act(() => {
    result.current.beginReply();
    result.current.finishReply('完整的一句。');
  });
  await act(async () => emit(new Uint8Array(4800)));
  await act(async () => resolve('/api/tts/audio/live.wav'));
  act(() => result.current.replay());
  await waitFor(() => expect(played[0]).toContain('live.wav'));
  expect(liveSpeech).toHaveBeenCalledOnce();
  expect(request).not.toHaveBeenCalled();
  act(() => result.current.stop());
});
