import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from './CompanionApp';

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

beforeEach(() => {
  HTMLElement.prototype.scrollIntoView = vi.fn();
  HTMLElement.prototype.scrollTo = vi.fn();
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} }),
  );
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const value = url.endsWith('/auth/status')
        ? { required: false, authenticated: true }
        : url.endsWith('/settings')
          ? { configured: true }
          : url.endsWith('/features')
            ? { tts: { enabled: false }, reminders: { enabled: false }, tools: {}, memory: {} }
            : url.endsWith('/work/output')
              ? { workspace: null }
              : url.includes('/work/events')
                ? { events: [] }
                : url.endsWith('/model-default') || /\/conversations\/[^/]+\/model$/.test(url)
                  ? null
                  : url.includes('/reminders/poll')
                    ? { event: null }
                    : [];
      return new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } });
    }),
  );
});

it('shows the observation time and source for a weather care reminder', async () => {
  const fallback = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) =>
    String(input).includes('/reminders/poll')
      ? new Response(
          JSON.stringify({
            event: {
              id: 'weather-reminder',
              text: '南宁有小雨，出门记得带伞。',
              voice: false,
              created_at: new Date().toISOString(),
              weather: {
                city: '南宁',
                observed_at: '2026-10-23T12:00',
                sources: [{ title: '天气来源', url: 'https://api.open-meteo.com/' }],
              },
            },
          }),
          { headers: { 'content-type': 'application/json' } },
        )
      : fallback(input, init),
  );
  render(<App />);
  await screen.findByText('南宁有小雨，出门记得带伞。');
  expect(screen.getByText(/天气数据：2026-10-23T12:00/)).toBeTruthy();
  expect(screen.getByRole('link', { name: '天气来源' }).getAttribute('href')).toBe(
    'https://api.open-meteo.com/',
  );
});

it('uses a keyboard accessible sliding search selector and one compact saved-service test button', async () => {
  render(<App />);
  await screen.findByText('模型已配置');
  fireEvent.click(screen.getAllByRole('button', { name: '工具设置' })[0]);
  await screen.findByRole('tab', { name: '工具服务' });
  expect(screen.queryByLabelText('搜索测试关键词')).toBeNull();
  const selector = screen.getByRole('combobox', { name: '搜索服务' });
  expect(selector.tagName).toBe('BUTTON');
  fireEvent.keyDown(selector, { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: /Wikipedia/ }));
  fireEvent.click(screen.getByRole('button', { name: '测试搜索连接' }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      '/api/tools/run',
      expect.objectContaining({
        body: JSON.stringify({
          name: 'web_search',
          args: { query: 'Python programming language', limit: 3 },
        }),
      }),
    ),
  );
});

it('grants a file folder from settings without also saving unrelated tool settings', async () => {
  render(<App />);
  await screen.findByText('模型已配置');
  fireEvent.click(screen.getAllByRole('button', { name: '工具设置' })[0]);
  fireEvent.click(await screen.findByText('本机文件夹授权', { exact: true }));
  fireEvent.change(screen.getByLabelText('本机文件夹完整路径'), { target: { value: 'D:\\work' } });
  fireEvent.click(screen.getByRole('button', { name: '授权此文件夹' }));
  await screen.findByText('工作文件夹已授权。');
  expect(
    vi
      .mocked(fetch)
      .mock.calls.some(([url, options]) => url === '/api/features' && options?.method === 'PATCH'),
  ).toBe(false);
});

it('sends a new conversation with its selected saved connection even when the global default is unconfigured', async () => {
  const fallback = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, options) => {
    const url = String(input);
    if (url.endsWith('/settings'))
      return new Response(
        JSON.stringify({
          configured: false,
          model: '',
          base_url: 'https://default.invalid/v1',
          protocol: 'openai',
          provider: 'custom',
          temperature: 0.7,
          timeout: 45,
          max_tokens: 1800,
        }),
      );
    if (url.endsWith('/model-options'))
      return new Response(
        JSON.stringify([
          {
            id: 'secondary',
            label: '服务二',
            configured: true,
            models: [{ id: 'second-model', efforts: ['default', 'high'] }],
          },
        ]),
      );
    if (url.endsWith('/chat'))
      return new Response(
        'event: done\ndata: {"id":"reply","conversation_id":"new","role":"assistant","status":"complete","content":"收到","created_at":"2026-10-24T03:00:00Z"}\n\n',
        { headers: { 'content-type': 'text/event-stream' } },
      );
    return fallback(input, options);
  });
  render(<App />);
  const picker = await screen.findByRole('combobox', { name: '当前会话模型' });
  await waitFor(() => expect(picker).toHaveProperty('disabled', false));
  fireEvent.keyDown(picker, { key: 'ArrowDown' });
  fireEvent.click(await screen.findByRole('option', { name: 'second-model' }));
  fireEvent.change(screen.getByLabelText('给瞬光伴行发送消息'), { target: { value: '使用选定模型' } });
  fireEvent.click(screen.getByRole('button', { name: '发送消息' }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      '/api/chat',
      expect.objectContaining({
        body: JSON.stringify({
          conversation_id: null,
          content: '使用选定模型',
          model_choice: { profile_id: 'secondary', model: 'second-model', effort: 'high' },
        }),
      }),
    ),
  );
});

it('keeps navigation accessible when collapsed and restores the choice after reopening the app', async () => {
  const view = render(<App />);
  await screen.findByText('模型已配置');
  fireEvent.click(screen.getByRole('button', { name: '收起侧栏' }));
  expect(screen.getByRole('button', { name: '展开侧栏' }).getAttribute('aria-expanded')).toBe('false');
  expect(screen.getByRole('button', { name: '工作台' })).toBeTruthy();
  view.unmount();
  render(<App />);
  await waitFor(() => expect(screen.getByRole('button', { name: '展开侧栏' })).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: '展开侧栏' }));
  expect(screen.getByRole('button', { name: '收起侧栏' }).getAttribute('aria-expanded')).toBe('true');
});

it('lets the user disable motion and remembers that setting after reopening', async () => {
  const view = render(<App />);
  await screen.findByText('模型已配置');
  fireEvent.click(screen.getByRole('button', { name: '沉浸光效设置' }));
  const toggle = await screen.findByRole('switch', { name: '沉浸光效' });
  expect(toggle.getAttribute('aria-checked')).toBe('true');
  fireEvent.click(toggle);
  expect(toggle.getAttribute('aria-checked')).toBe('false');
  view.unmount();
  render(<App />);
  await screen.findByText('模型已配置');
  fireEvent.click(screen.getByRole('button', { name: '沉浸光效设置' }));
  expect((await screen.findByRole('switch', { name: '沉浸光效' })).getAttribute('aria-checked')).toBe(
    'false',
  );
});

it('switches backgrounds without losing the draft and restores the selected style after reopening', async () => {
  const view = render(<App />);
  await screen.findByText('模型已配置');
  fireEvent.change(screen.getByLabelText('给瞬光伴行发送消息'), { target: { value: '待发送的草稿' } });
  fireEvent.click(screen.getByRole('button', { name: '沉浸光效设置' }));
  expect((await screen.findByRole('radio', { name: /Dark Veil/ })) as HTMLInputElement).toHaveProperty(
    'checked',
    true,
  );
  fireEvent.click(screen.getByRole('radio', { name: /Gradient Blinds/ }));
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  expect((screen.getByLabelText('给瞬光伴行发送消息') as HTMLTextAreaElement).value).toBe('待发送的草稿');
  view.unmount();
  render(<App />);
  await screen.findByText('模型已配置');
  fireEvent.click(screen.getByRole('button', { name: '沉浸光效设置' }));
  expect((await screen.findByRole('radio', { name: /Gradient Blinds/ })) as HTMLInputElement).toHaveProperty(
    'checked',
    true,
  );
});

it('shows a background file task waiting for confirmation in the compact header', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, options) => {
    const url = String(input);
    const value = url.endsWith('/conversations')
      ? [{ id: 'c1', title: '文件验收' }]
      : url.includes('/work/tasks?')
        ? [{ id: 't1', title: '资料总结', status: 'waiting_limit', steps: [], context: {}, error: '' }]
        : null;
    return value
      ? new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })
      : original(input, options);
  });
  render(<App />);
  fireEvent.click(await screen.findByRole('button', { name: '文件验收' }));
  expect(
    await within(screen.getByRole('region', { name: '当前状态' })).findByText('文件任务 · 等待确认继续'),
  ).toBeTruthy();
});

it('falls back from an obsolete background preference and keeps all styles usable without WebGL', async () => {
  localStorage.setItem('shunguang-ui-background', 'removed-style');
  render(<App />);
  await screen.findByText('模型已配置');
  fireEvent.click(screen.getByRole('button', { name: '沉浸光效设置' }));
  expect(await screen.findByRole('radio', { name: /Dark Veil/ })).toHaveProperty('checked', true);
  fireEvent.click(screen.getByRole('radio', { name: /Aurora/ }));
  expect(screen.getByRole('radio', { name: /Aurora/ })).toHaveProperty('checked', true);
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  fireEvent.change(screen.getByLabelText('给瞬光伴行发送消息'), { target: { value: '静态回退时也能输入' } });
  expect(screen.getByRole('button', { name: '发送消息' })).toHaveProperty('disabled', false);
});

it('lets the user change backgrounds when browser preference storage is unavailable', async () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('Storage blocked');
  });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('Storage blocked');
  });
  render(<App />);
  await screen.findByText('模型已配置');
  fireEvent.click(screen.getByRole('button', { name: '沉浸光效设置' }));
  fireEvent.click(await screen.findByRole('radio', { name: /Aurora/ }));
  expect(screen.getByRole('radio', { name: /Aurora/ })).toHaveProperty('checked', true);
});
