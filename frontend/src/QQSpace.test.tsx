import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { request } from './api';
import { QQSpace } from './QQSpace';
import { QQChats } from './QQChats';

vi.mock('./api', () => ({ request: vi.fn() }));
afterEach(cleanup);

test('desktop lite keeps Windows credential and keep-awake guidance', async () => {
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(
      path === '/qq/state'
        ? {
            deployment_mode: 'desktop',
            local_knowledge: false,
            connection: {
              enabled: false,
              token: '',
              url: 'ws://127.0.0.1:3001',
              bot_id: '',
              retention_days: 30,
              model_choice: null,
            },
            status: 'disabled',
            has_token: false,
            error: '',
            owner: '',
            last_event: null,
            policies: [],
            vision_profiles: [],
          }
        : [],
    ),
  );
  render(<QQSpace />);
  expect(await screen.findByText(/Token 使用当前 Windows 账户加密/)).toBeTruthy();
  expect(screen.getByText(/电脑需保持唤醒/)).toBeTruthy();
});

test('each QQ chat has an independently saved sticker switch', async () => {
  const enabled: Record<string, boolean> = { '30001': true, '30002': true };
  vi.mocked(request).mockImplementation((path, options) => {
    if (path.startsWith('/qq/chats?'))
      return Promise.resolve({
        items: [
          { kind: 'private', target: '30001', name: '甲', count: 1, stamp: 1 },
          { kind: 'private', target: '30002', name: '乙', count: 1, stamp: 1 },
        ],
        total: 2,
      });
    const id = path.includes('30001') ? '30001' : '30002';
    if (options?.method === 'PATCH') {
      enabled[id] = JSON.parse(options.body as string).enabled;
      return Promise.resolve({ stickers: enabled[id] });
    }
    return Promise.resolve({ items: [], has_more: false, next_cursor: '', stickers: enabled[id] });
  });
  render(<QQChats />);
  fireEvent.click(await screen.findByRole('button', { name: /甲/ }));
  const checkbox = await screen.findByLabelText('回复附带表情包');
  expect((checkbox as HTMLInputElement).checked).toBe(true);
  fireEvent.click(checkbox);
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith('/qq/chats/private/30001/stickers', {
      method: 'PATCH',
      body: JSON.stringify({ enabled: false }),
    }),
  );
  await waitFor(() =>
    expect((screen.getByLabelText('回复附带表情包') as HTMLInputElement).checked).toBe(false),
  );
  fireEvent.click(screen.getByRole('button', { name: /乙/ }));
  await waitFor(() =>
    expect((screen.getByLabelText('回复附带表情包') as HTMLInputElement).checked).toBe(true),
  );
});

test('QQ chat shows received images, reply sticker and delivery state in its own tab', async () => {
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(
      path === '/qq/state'
        ? {
            connection: {
              enabled: false,
              token: '',
              url: 'ws://127.0.0.1:3001',
              bot_id: '10001',
              retention_days: 30,
              model_choice: null,
            },
            status: 'disabled',
            owner: '',
            policies: [],
            vision_profiles: [],
            chat_view_ready: true,
          }
        : path.startsWith('/qq/peers/private')
          ? {
              items: [
                {
                  kind: 'private',
                  target: '30001',
                  name: '测试联系人',
                  policy: { collect: true, chat: 'mention', stickers: true },
                },
              ],
              total: 1,
            }
          : path.startsWith('/qq/chats/private/30001')
            ? {
                items: [
                  {
                    id: 'one',
                    author: '30001',
                    name: '测试联系人',
                    stamp: 1,
                    text: '这是什么',
                    reply: '一只猫',
                    state: 'uncertain',
                    error: '发送未确认',
                    images: [
                      {
                        id: 'image',
                        url: '/api/qq/chats/private/30001/images/image',
                        description: '猫',
                        error: '',
                      },
                    ],
                    sticker: {
                      id: 'test',
                      url: '/api/resources/character/stickers/49-red-daily-by-your-side.png',
                      caption: '在呢',
                      persona: 'red',
                      scene: 'neutral',
                    },
                  },
                ],
                next_cursor: 'one',
                has_more: false,
              }
            : [],
    ),
  );
  render(<QQSpace />);
  fireEvent.click(await screen.findByRole('button', { name: '聊天管理' }));
  fireEvent.click(await screen.findByRole('button', { name: /测试联系人/ }));
  expect(await screen.findByText('一只猫')).toBeTruthy();
  expect(screen.getByAltText('QQ 收到的图片')).toBeTruthy();
  expect(screen.getByAltText('叶瞬光：在呢')).toBeTruthy();
  expect(
    within(screen.getByRole('region', { name: '最近一条消息的处理状态' })).getByText(/发送结果待确认/),
  ).toBeTruthy();
});

test('latest QQ status is tied to the current chat and the newest page', async () => {
  vi.mocked(request).mockImplementation((path) => {
    if (path.startsWith('/qq/chats?')) {
      return Promise.resolve({
        items: [
          { kind: 'group', target: '20001', name: '测试群甲', count: 2, stamp: 2 },
          { kind: 'group', target: '20002', name: '测试群乙', count: 0, stamp: 0 },
        ],
        total: 2,
      });
    }
    const latest = path.endsWith('before=');
    const error = latest ? '这条消息未 @ 机器人或使用指令。' : '旧的超时记录';
    return Promise.resolve({
      items: path.includes('20002')
        ? []
        : [
            {
              id: latest ? 'new' : 'old',
              author: '30001',
              name: '测试成员',
              stamp: latest ? 2 : 1,
              text: latest ? '新消息' : '旧消息',
              reply: '',
              state: latest ? 'collected' : 'failed',
              error,
              images: [],
            },
          ],
      has_more: latest,
      next_cursor: latest ? 'new' : '',
    });
  });
  render(<QQChats />);
  fireEvent.change(screen.getByRole('textbox', { name: '搜索 QQ 聊天名称或号码' }), {
    target: { value: '测试群' },
  });
  fireEvent.click(await screen.findByRole('button', { name: /测试群甲/ }));
  const status = () => screen.getByRole('region', { name: '最近一条消息的处理状态' });
  await screen.findByText('新消息');
  expect(within(status()).getByText(/未 @ 机器人/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: '更早消息' }));
  await screen.findByText('旧消息');
  expect(screen.queryByRole('region', { name: '最近一条消息的处理状态' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: '最新消息' }));
  await screen.findByText('新消息');
  expect(within(status()).getByText(/未 @ 机器人/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: /测试群乙/ }));
  expect(await screen.findByText(/检查 QQ 连接及此聊天的采集设置/)).toBeTruthy();
  expect(screen.queryByText(/未 @ 机器人/)).toBeNull();
});

test('QQ panel shows safe defaults and explains browser independent background processing', async () => {
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(
      path === '/qq/state'
        ? {
            connection: {
              enabled: false,
              url: 'ws://127.0.0.1:3001',
              token: '',
              bot_id: '',
              retention_days: 30,
              model_choice: null,
            },
            has_token: false,
            status: 'disabled',
            error: '',
            owner: '',
            last_event: null,
            policies: [],
            vision_profiles: [],
          }
        : path.startsWith('/qq/peers/')
          ? { items: [], total: 0 }
          : [],
    ),
  );
  render(<QQSpace />);
  await waitFor(() => expect(screen.getByLabelText('机器人 QQ 号')).toBeTruthy());
  expect((screen.getByLabelText('启用 QQ 连接') as HTMLInputElement).checked).toBe(false);
  expect((screen.getByLabelText('原始记录保留天数') as HTMLInputElement).value).toBe('30');
  expect(screen.getByText(/关闭浏览器后继续运行/)).toBeTruthy();
  expect(screen.getByText(/主人：尚未绑定/)).toBeTruthy();
});

test('changing group chat mode preserves an independent summary-only schedule and panel destination', async () => {
  const policy = {
    collect: true,
    chat: 'off',
    knowledge: true,
    images: false,
    vision_profile: '',
    vision_signature: '',
    allow_group_send: false,
    schedule: 'daily',
    daily_time: '22:00',
    interval_hours: 6,
    window: 'incremental',
    window_start: '00:00',
    window_end: '23:59',
    delivery: 'panel',
  };
  vi.mocked(request).mockImplementation((path, options) =>
    Promise.resolve(
      path === '/qq/state'
        ? {
            connection: {
              enabled: false,
              token: '',
              url: 'ws://127.0.0.1:3001',
              bot_id: '10001',
              retention_days: 30,
              model_choice: null,
            },
            status: 'disabled',
            has_token: false,
            error: '',
            owner: '',
            last_event: null,
            policies: [],
            vision_profiles: [],
          }
        : path.startsWith('/qq/peers/group')
          ? { items: [{ kind: 'group', target: '20001', name: '测试群', policy }], total: 1 }
          : path.startsWith('/qq/policies/')
            ? JSON.parse(options?.body as string)
            : [],
    ),
  );
  render(<QQSpace />);
  fireEvent.click(await screen.findByRole('button', { name: '聊天管理' }));
  fireEvent.click(screen.getByRole('button', { name: '群聊' }));
  fireEvent.click(await screen.findByRole('button', { name: /测试群/ }));
  fireEvent.click(screen.getByRole('button', { name: '设置' }));
  expect((screen.getByLabelText('聊天模式') as HTMLSelectElement).value).toBe('off');
  fireEvent.change(screen.getByLabelText('聊天模式'), { target: { value: 'mention' } });
  fireEvent.click(screen.getByRole('button', { name: '保存此范围设置' }));
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith('/qq/policies/group/20001', {
      method: 'PUT',
      body: JSON.stringify({ ...policy, chat: 'mention' }),
    }),
  );
  fireEvent.click(screen.getByRole('button', { name: '群摘要' }));
  expect((screen.getByLabelText('定时总结') as HTMLSelectElement).value).toBe('daily');
  expect((screen.getByLabelText('定时摘要去向') as HTMLSelectElement).value).toBe('panel');
  expect((screen.getByLabelText('单独允许摘要发回此群') as HTMLInputElement).checked).toBe(false);
});
