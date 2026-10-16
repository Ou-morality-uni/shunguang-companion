import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { CloudVoiceManager } from './CloudVoiceManager';
import { request, type Features } from './api';

vi.mock('./api', () => ({ request: vi.fn() }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
const features = {
  tts: {
    provider: 'aliyun',
    model: 'qwen-audio-3.1-tts-flash',
    has_api_key: true,
    external_reference_enabled: true,
    voice: '',
  },
} as Features;

it('creates once, saves the returned selection and never submits the containing settings form', async () => {
  const onSaved = vi.fn(),
    submit = vi.fn();
  let finish: (value: unknown) => void = () => {};
  vi.mocked(request).mockImplementation((url) =>
    url === '/tts/register'
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : Promise.resolve({ voices: [] }),
  );
  render(
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <CloudVoiceManager dirty={false} features={features} onSaved={onSaved} />
    </form>,
  );
  fireEvent.click(screen.getByText('创建并保存云端音色'));
  await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
  expect(submit).not.toHaveBeenCalled();
  expect(screen.getByText('创建并保存云端音色')).toHaveProperty('disabled', true);
  const saved = { ...features, tts: { ...features.tts, voice: 'cloud-voice' } };
  await act(async () => finish({ voice: 'cloud-voice', features: saved }));
  expect(onSaved).toHaveBeenCalledWith(saved);
  expect(screen.getByRole('status').textContent).toContain('无需原 MP3');
});

it('shows multiple cloud voices, persists selection and requires confirmation to delete', async () => {
  const onSaved = vi.fn();
  const voices = [
    { voice: 'v1', name: '声音一', model: features.tts.model },
    { voice: 'v2', name: '声音二', model: features.tts.model },
  ];
  vi.mocked(request).mockImplementation((url) =>
    Promise.resolve(url === '/tts/voices' ? { voices } : features),
  );
  render(<CloudVoiceManager dirty={false} features={features} onSaved={onSaved} />);
  fireEvent.click(screen.getByText('刷新云端列表'));
  await screen.findByText('声音二');
  fireEvent.click(screen.getAllByText('选择并保存')[1]);
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
  expect(request).toHaveBeenCalledWith(
    '/tts/voices/select',
    expect.objectContaining({ body: JSON.stringify({ voice: 'v2' }) }),
  );
  fireEvent.click(screen.getAllByText('删除')[0]);
  expect(request).not.toHaveBeenCalledWith('/tts/voices/delete', expect.anything());
  fireEvent.click(screen.getByText('确认删除该音色'));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      '/tts/voices/delete',
      expect.objectContaining({ body: JSON.stringify({ voice: 'v1' }) }),
    ),
  );
});

it('blocks cloud mutations while credentials or model changes are unsaved', () => {
  render(<CloudVoiceManager dirty features={features} onSaved={vi.fn()} />);
  fireEvent.click(screen.getByText('创建并保存云端音色'));
  expect(request).not.toHaveBeenCalled();
});

it('does not present a connection-only probe as verified synthesis', async () => {
  vi.mocked(request).mockResolvedValue({
    ok: true,
    synthesis_verified: false,
    message: '连接已建立，需试听验证。',
  });
  render(<CloudVoiceManager dirty={false} features={features} onSaved={vi.fn()} />);
  fireEvent.click(screen.getByText('检查百炼连接'));
  await screen.findByText('连接已建立，需试听验证。');
});

it('requires a current model for new voices while retaining legacy list access', () => {
  const legacy = { ...features, tts: { ...features.tts, model: 'qwen3-tts-vc-realtime-2026-01-15' } };
  render(<CloudVoiceManager dirty={false} features={legacy} onSaved={vi.fn()} />);
  expect(screen.getByText('创建并保存云端音色')).toHaveProperty('disabled', true);
  expect(screen.getByText('刷新云端列表')).toHaveProperty('disabled', false);
});
