import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useAudioQueue } from './useAudioQueue';
import { request, type Features } from './api';
import { streamSpeech } from './speechStream';

vi.mock('./api', () => ({ request: vi.fn() }));
vi.mock('./speechStream', async (original) => ({
  ...(await original<typeof import('./speechStream')>()),
  streamSpeech: vi.fn(),
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

it('prefetches next sentence but plays in text order even if the second request finishes first', async () => {
  const pending = pendingRequests();
  const { result } = renderHook(() => useAudioQueue(settings));
  act(() => result.current.enqueue('第一句。第二句。'));
  expect(pending.map((item) => item.text)).toEqual(['第一句。', '第二句。']);
  await act(async () => pending[1].resolve({ audio_url: '/api/tts/audio/second.wav' }));
  expect(played).toEqual([]);
  await act(async () => pending[0].resolve({ audio_url: '/api/tts/audio/first.wav' }));
  expect(played[0]).toContain('first.wav');
  await act(async () => document.querySelector('audio')!.dispatchEvent(new Event('ended')));
  expect(played[1]).toContain('second.wav');
  act(() => result.current.stop());
});

it('starts during text generation, flushes a timed tail, and does not enqueue the final text twice', async () => {
  vi.useFakeTimers();
  const pending = pendingRequests();
  const { result } = renderHook(() => useAudioQueue(settings));
  act(() => {
    result.current.beginReply();
    result.current.appendReply('第一句。还没结束');
  });
  expect(pending.map((item) => item.text)).toEqual(['第一句。']);
  await act(async () => vi.advanceTimersByTimeAsync(700));
  expect(pending.map((item) => item.text)).toEqual(['第一句。', '还没结束']);
  act(() => result.current.finishReply('第一句。还没结束'));
  expect(pending).toHaveLength(2);
  act(() => result.current.stop());
  await act(async () => pending.forEach((item) => item.resolve({ audio_url: '/api/tts/audio/old.wav' })));
});

it('aborts every old request and rejects late audio after a new turn', async () => {
  const pending = pendingRequests();
  const { result } = renderHook(() => useAudioQueue(settings));
  act(() => {
    result.current.beginReply();
    result.current.appendReply('旧句一。旧句二。');
  });
  act(() => {
    result.current.beginReply();
    result.current.appendReply('新句。');
  });
  expect(pending.slice(0, 2).every((item) => item.signal.aborted)).toBe(true);
  await act(async () =>
    pending.slice(0, 2).forEach((item) => item.resolve({ audio_url: '/api/tts/audio/old.wav' })),
  );
  await waitFor(() => expect(pending).toHaveLength(3));
  await act(async () => pending[2].resolve({ audio_url: '/api/tts/audio/new.wav' }));
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
  await act(async () => result.current.enqueue('实时声音。'));
  act(() => emit(new Uint8Array([1, 0, 2, 0])));
  expect(nodes[0].start).toHaveBeenCalledOnce();
  expect(result.current.playing).toBe(true);
  act(() => result.current.stop());
  expect(signal!.aborted).toBe(true);
  expect(nodes[0].stop).toHaveBeenCalledOnce();
  await act(async () => finish('/api/tts/audio/late.wav'));
  expect(played).toEqual([]);
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
