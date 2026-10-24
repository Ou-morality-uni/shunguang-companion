import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { request } from './api';
import { VoiceInput } from './VoiceInput';

const audio = vi.hoisted(() => ({ setInputActive: vi.fn() }));
vi.mock('./useAudioQueue', () => ({ useCompanionAudio: () => audio }));
vi.mock('./api', () => ({ request: vi.fn() }));
const settings = {
  enabled: true,
  configured: true,
  base_url: 'https://example.com/v1',
  model: 'test',
  profile_id: '',
  timeout: 60,
  has_api_key: true,
};
let stopTrack: ReturnType<typeof vi.fn>;
let getMedia: ReturnType<typeof vi.fn>;
let recorders: Recorder[];
class Recorder {
  static isTypeSupported = () => true;
  state = 'inactive';
  mimeType = 'audio/webm';
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor() {
    recorders.push(this);
  }
  start() {
    this.state = 'recording';
  }
  stop() {
    this.state = 'inactive';
    this.ondataavailable?.({ data: new Blob(['audio'], { type: this.mimeType }) });
    this.onstop?.();
  }
}
function mount(composer = { getState: () => ({ text: '原草稿' }), setText: vi.fn() }) {
  return {
    ...render(
      <VoiceInput
        settings={settings}
        composer={composer}
        disabled={false}
        onSettings={vi.fn()}
        onBusyChange={vi.fn()}
      />,
    ),
    composer,
  };
}
beforeEach(() => {
  vi.clearAllMocks();
  recorders = [];
  stopTrack = vi.fn();
  getMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] });
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: getMedia } });
  vi.stubGlobal('MediaRecorder', Recorder);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it('discards an in-flight transcript after switching away and never inserts it into the next conversation', async () => {
  let finish!: (value: { text: string }) => void;
  vi.mocked(request).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const first = mount();
  fireEvent.click(screen.getByRole('button', { name: '开始语音输入' }));
  fireEvent.click(await screen.findByRole('button', { name: '结束录音并转写' }));
  await screen.findByRole('button', { name: '正在识别语音' });
  const signal = vi.mocked(request).mock.calls[0][1]!.signal!;
  first.unmount();
  const second = mount();
  await act(async () => finish({ text: '不应填到另一个聊天' }));
  expect(signal.aborted).toBe(true);
  expect(first.composer.setText).not.toHaveBeenCalled();
  expect(second.composer.setText).not.toHaveBeenCalled();
  expect(stopTrack).toHaveBeenCalledOnce();
});

it('closes a late microphone permission result after the user cancels the permission wait', async () => {
  let allow!: (value: unknown) => void;
  getMedia.mockImplementation(
    () =>
      new Promise((resolve) => {
        allow = resolve;
      }),
  );
  mount();
  fireEvent.click(screen.getByRole('button', { name: '开始语音输入' }));
  fireEvent.click(screen.getByRole('button', { name: '取消语音输入' }));
  await act(async () => allow({ getTracks: () => [{ stop: stopTrack }] }));
  expect(stopTrack).toHaveBeenCalledOnce();
  expect(recorders).toHaveLength(0);
  expect(request).not.toHaveBeenCalled();
  expect(audio.setInputActive).toHaveBeenLastCalledWith(false);
});

it('returns to an editable text workflow when microphone permission is denied', async () => {
  getMedia.mockRejectedValue(new DOMException('denied', 'NotAllowedError'));
  const { composer } = mount();
  fireEvent.click(screen.getByRole('button', { name: '开始语音输入' }));
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('未获得麦克风权限'));
  expect(screen.getByRole('button', { name: '开始语音输入' })).toHaveProperty('disabled', false);
  expect(composer.setText).not.toHaveBeenCalled();
  expect(audio.setInputActive).toHaveBeenLastCalledWith(false);
});
