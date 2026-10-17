import { afterEach, expect, it, vi } from 'vitest';
import { SpeechSegmenter, streamSpeech, PcmPlayback, liveSpeech } from './speechStream';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it('segments punctuation, length and timed tails without repeating or losing text', () => {
  const segmenter = new SpeechSegmenter();
  expect(segmenter.push('你好，')).toEqual([]);
  expect(segmenter.push('今天好吗？第二句')).toEqual(['你好，今天好吗？']);
  expect(segmenter.push('', true)).toEqual(['第二句']);
  expect(segmenter.push('', true)).toEqual([]);
  const text = '甲'.repeat(179) + '😊' + '乙'.repeat(220);
  const chunks = segmenter.push(text, true);
  expect(chunks.join('')).toBe(text);
  expect(chunks.every((part) => part.length <= 180)).toBe(true);
  expect(segmenter.push('3.14 is pi. Next.', true)).toEqual(['3.14 is pi.', 'Next.']);
  const live = new SpeechSegmenter(40, true);
  expect([...live.push('Hello ', true), ...live.push('world.\n', true)].join('')).toBe('Hello world.\n');
});

function response(frames: string[]) {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const frame of frames) controller.enqueue(encoder.encode(frame));
        controller.close();
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  );
}

it('delivers audio before done across fragmented SSE frames', async () => {
  const order: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(
        response([
          'event: au',
          'dio\ndata: {"pcm":"AQA=","sample_rate":24000}\n\n',
          'event: done\ndata: {"audio_url":"/api/tts/audio/test.wav"}\n\n',
        ]),
      ),
  );
  const result = await streamSpeech('文字', new AbortController().signal, (pcm) => {
    expect([...pcm]).toEqual([1, 0]);
    order.push('audio');
  });
  order.push(result);
  expect(order).toEqual(['audio', '/api/tts/audio/test.wav']);
});

it('rejects early EOF and surfaced upstream errors instead of treating partial audio as complete', async () => {
  const audio = 'event: audio\ndata: {"pcm":"AQA=","sample_rate":24000}\n\n';
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(response([audio]))
      .mockResolvedValueOnce(response([audio, 'event: error\ndata: {"message":"额度不足"}\n\n'])),
  );
  await expect(streamSpeech('文字', new AbortController().signal, vi.fn())).rejects.toThrow('提前结束');
  await expect(streamSpeech('文字', new AbortController().signal, vi.fn())).rejects.toThrow('额度不足');
});

it('reassembles odd PCM byte boundaries, schedules in order and stops all scheduled sound', async () => {
  const samples: Float32Array[] = [];
  const nodes: { start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> }[] = [];
  const context = {
    currentTime: 10,
    createBuffer: (_channels: number, length: number, rate: number) => {
      const data = new Float32Array(length);
      samples.push(data);
      return { duration: length / rate, getChannelData: () => data };
    },
    createBufferSource: () => {
      const node = {
        playbackRate: { value: 1 },
        connect: vi.fn(),
        disconnect: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
        onended: null,
      };
      nodes.push(node);
      return node;
    },
  };
  const player = new PcmPlayback(context as unknown as AudioContext, {} as AudioNode, 1);
  player.push(new Uint8Array([0]));
  expect(nodes).toHaveLength(0);
  player.push(new Uint8Array([128, 255, 127]));
  player.push(new Uint8Array([1, 0]));
  expect(samples[0][0]).toBe(-1);
  expect(samples[0][1]).toBeCloseTo(32767 / 32768);
  expect(nodes[1].start.mock.calls[0][0]).toBeGreaterThan(nodes[0].start.mock.calls[0][0]);
  const ended = player.finish();
  player.stop();
  await ended;
  expect(nodes.every((node) => node.stop.mock.calls.length === 1)).toBe(true);
});

it('uses one duplex socket, receives PCM before finish, and rejects a premature close', async () => {
  const sockets: Socket[] = [];
  class Socket {
    static OPEN = 1;
    readyState = 0;
    binaryType = '';
    onopen = () => {};
    onmessage = (_event: { data: unknown }) => {};
    onclose = () => {};
    send = vi.fn();
    close = vi.fn();
    constructor(public url: URL) {
      sockets.push(this);
    }
  }
  vi.stubGlobal('WebSocket', Socket);
  const audio = vi.fn();
  const stream = liveSpeech(new AbortController().signal, audio);
  stream.push('第一句。');
  stream.push('第二句。');
  const socket = sockets[0];
  expect(socket.url.pathname).toBe('/api/tts/live');
  socket.readyState = 1;
  socket.onopen();
  expect(socket.send.mock.calls.map(([raw]) => JSON.parse(raw).text)).toEqual(['第一句。', '第二句。']);
  socket.onmessage({ data: new Uint8Array([1, 0]).buffer });
  expect(audio).toHaveBeenCalledOnce();
  stream.finish();
  socket.onmessage({ data: JSON.stringify({ type: 'done', audio_url: '/api/tts/audio/test.wav' }) });
  await expect(stream.promise).resolves.toBe('/api/tts/audio/test.wav');
  expect(sockets).toHaveLength(1);
  const broken = liveSpeech(new AbortController().signal, vi.fn());
  sockets[1].onclose();
  await expect(broken.promise).rejects.toThrow('提前中断');
});

it('buffers network bursts, schedules them contiguously and flushes short replies without waiting', async () => {
  vi.useFakeTimers();
  const nodes: { start: ReturnType<typeof vi.fn>; onended: (() => void) | null }[] = [];
  const context = {
    currentTime: 0,
    createBuffer: (_channels: number, length: number, rate: number) => ({
      duration: length / rate,
      getChannelData: () => new Float32Array(length),
    }),
    createBufferSource: () => {
      const node = {
        playbackRate: { value: 1 },
        connect: vi.fn(),
        disconnect: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
        onended: null,
      };
      nodes.push(node);
      return node;
    },
  };
  const player = new PcmPlayback(context as unknown as AudioContext, {} as AudioNode, 1, 0.35);
  player.push(new Uint8Array(4800));
  await vi.advanceTimersByTimeAsync(100);
  player.push(new Uint8Array(12000));
  expect(nodes).toHaveLength(2);
  expect(nodes[1].start.mock.calls[0][0]).toBeCloseTo(nodes[0].start.mock.calls[0][0] + 0.1);
  context.currentTime = 0.37; // Do not add a start delay while 15ms of scheduled audio remains.
  player.push(new Uint8Array(4800));
  expect(nodes[2].start.mock.calls[0][0]).toBeCloseTo(0.385);
  context.currentTime = 1; // Starvation: rebuild a buffer instead of scheduling each tiny packet.
  player.push(new Uint8Array(480));
  expect(nodes).toHaveLength(3);
  const finished = player.finish();
  expect(nodes).toHaveLength(4);
  nodes.forEach((node) => node.onended?.());
  await finished;
  player.stop();
  await vi.advanceTimersByTimeAsync(1000);
  expect(nodes).toHaveLength(4);
});
