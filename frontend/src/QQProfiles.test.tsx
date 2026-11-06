import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { request } from './api';
import { QQProfiles } from './QQProfiles';
import { QQSpace } from './QQSpace';

vi.mock('./api', () => ({ request: vi.fn() }));
afterEach(cleanup);

test('returning from a newly saved manual member shows that member without a bridge refresh', async () => {
  let stored = false;
  vi.mocked(request).mockImplementation((path, options) => {
    if (options?.method === 'PUT') {
      stored = true;
      return Promise.resolve({
        bot: '10001',
        revision: 1,
        entries: JSON.parse(options.body as string).entries,
      });
    }
    if (path.startsWith('/qq/members/'))
      return Promise.resolve({
        items: stored ? [{ user_id: '40001', name: '提前建档', card: '', source: 'manual' }] : [],
        total: stored ? 1 : 0,
        stale: true,
        refreshed: 0,
        notice: '离线名单',
      });
    return Promise.resolve({ bot: '10001', revision: 0, entries: [] });
  });
  render(<QQProfiles kind="group" target="20001" name="摄影群" onDirty={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: '成员' }));
  fireEvent.change(screen.getByLabelText('手动添加成员 QQ 号'), { target: { value: '40001' } });
  fireEvent.click(screen.getByRole('button', { name: '按 QQ 号建档' }));
  fireEvent.change(await screen.findByLabelText('称呼'), { target: { value: '提前建档' } });
  fireEvent.click(screen.getByRole('button', { name: '保存资料' }));
  await screen.findByText(/资料已保存/);
  fireEvent.click(screen.getByRole('button', { name: '返回成员列表' }));
  expect(await screen.findByRole('button', { name: /提前建档.*40001/ })).toBeTruthy();
});

test('custom and collapsed fields save together and reload in a private profile', async () => {
  let saved = {
    bot: '10001',
    revision: 0,
    entries: [] as { key: string; value: string; visibility: string }[],
  };
  vi.mocked(request).mockImplementation((path, options) => {
    if (options?.method === 'PUT') saved = { ...saved, ...JSON.parse(options.body as string), revision: 1 };
    return Promise.resolve(path.startsWith('/qq/profiles/') ? saved : []);
  });
  const first = render(<QQProfiles kind="private" target="30001" name="小林" onDirty={() => {}} />);
  fireEvent.change(await screen.findByLabelText('称呼'), { target: { value: '小林' } });
  fireEvent.click(screen.getByText(/更多资料/));
  fireEvent.change(screen.getByLabelText('兴趣偏好'), { target: { value: '摄影' } });
  fireEvent.click(screen.getByText(/更多资料/));
  fireEvent.click(screen.getByRole('button', { name: '新增记忆' }));
  fireEvent.change(screen.getByLabelText(/记忆标题 custom_/), { target: { value: '近期关注' } });
  fireEvent.change(screen.getByLabelText('记忆内容'), { target: { value: '周末的摄影展' } });
  fireEvent.click(screen.getByRole('button', { name: '保存资料' }));
  await screen.findByText(/资料已保存/);
  expect(saved.entries.map((e) => e.value)).toEqual(expect.arrayContaining(['小林', '摄影', '周末的摄影展']));
  expect(saved.entries.every((e) => e.visibility === 'self')).toBe(true);
  first.unmount();
  render(<QQProfiles kind="private" target="30001" name="小林" onDirty={() => {}} />);
  await waitFor(() => expect((screen.getByLabelText('称呼') as HTMLInputElement).value).toBe('小林'));
});

test('three main tabs preserve the target and protect unsaved profile edits', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  vi.mocked(request).mockImplementation((path) =>
    Promise.resolve(
      path === '/qq/state'
        ? {
            connection: {
              enabled: false,
              bot_id: '10001',
              url: 'ws://127.0.0.1:3001',
              token: '',
              retention_days: 30,
              model_choice: null,
            },
            status: 'disabled',
            owner: '',
            policies: [],
            vision_profiles: [],
            chat_view_ready: true,
            sticker_controls_ready: true,
          }
        : path.startsWith('/qq/peers/private')
          ? {
              items: [
                {
                  kind: 'private',
                  target: '30001',
                  name: '测试小林',
                  policy: { collect: false, chat: 'off', stickers: true },
                },
              ],
              total: 1,
            }
          : path.startsWith('/qq/profiles/')
            ? { bot: '10001', revision: 0, entries: [] }
            : path.startsWith('/qq/chats/')
              ? { items: [], has_more: false, next_cursor: '' }
              : [],
    ),
  );
  render(<QQSpace />);
  fireEvent.click(await screen.findByRole('button', { name: '聊天管理' }));
  fireEvent.click(await screen.findByRole('button', { name: /测试小林/ }));
  fireEvent.click(screen.getByRole('button', { name: '资料与记忆' }));
  fireEvent.change(await screen.findByLabelText('称呼'), { target: { value: '未保存称呼' } });
  fireEvent.click(screen.getByRole('button', { name: '群摘要' }));
  expect(confirm).toHaveBeenCalled();
  expect((screen.getByLabelText('称呼') as HTMLInputElement).value).toBe('未保存称呼');
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', { name: '群摘要' }));
  fireEvent.click(screen.getByRole('button', { name: '聊天管理' }));
  expect(await screen.findByRole('heading', { name: /测试小林/ })).toBeTruthy();
  confirm.mockRestore();
});

test('group member profile saves individual visibility and preserves a failed draft', async () => {
  vi.mocked(request).mockImplementation((path, options) => {
    if (options?.method === 'PUT') return Promise.reject(new Error('档案已在其他窗口修改，请重新读取'));
    if (path.startsWith('/qq/members/'))
      return Promise.resolve({
        items: [{ user_id: '30001', name: '小林', card: '摄影', source: 'bridge' }],
        total: 1,
        stale: false,
        refreshed: 1,
        notice: '',
      });
    if (path.startsWith('/qq/profiles/')) return Promise.resolve({ revision: 0, entries: [] });
    return Promise.resolve([]);
  });
  render(<QQProfiles kind="group" target="20001" name="摄影群" onDirty={() => {}} />);
  fireEvent.click(await screen.findByRole('button', { name: '成员' }));
  fireEvent.click(await screen.findByRole('button', { name: /摄影.*30001/ }));
  fireEvent.change(await screen.findByLabelText('称呼'), { target: { value: '林同学' } });
  fireEvent.change(screen.getByLabelText('称呼使用范围'), { target: { value: 'self' } });
  fireEvent.click(screen.getByRole('button', { name: '保存资料' }));
  expect((await screen.findByRole('alert')).textContent).toContain('其他窗口');
  expect((screen.getByLabelText('称呼') as HTMLInputElement).value).toBe('林同学');
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith(
      '/qq/profiles/group/20001?subject=30001',
      expect.objectContaining({ method: 'PUT', body: expect.stringContaining('"visibility":"self"') }),
    ),
  );
});
