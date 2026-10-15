import { afterEach, expect, it, vi } from 'vitest';
import { SpeechSegmenter, streamSpeech, PcmPlayback } from './speechStream';

afterEach(() => vi.unstubAllGlobals());

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
