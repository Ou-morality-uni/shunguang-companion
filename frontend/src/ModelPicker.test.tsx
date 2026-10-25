import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { afterEach, it, expect, vi } from 'vitest';
import { request } from './api';
import { ModelPicker } from './ModelPicker';
vi.mock('./api', () => ({ request: vi.fn() }));
afterEach(cleanup);
it('opens one model-and-reasoning menu and discovers other available service models', async () => {
  HTMLElement.prototype.scrollIntoView = vi.fn();
  const onChange = vi.fn();
  vi.mocked(request).mockImplementation(async (path) => {
    if (path === '/model-options')
      return [
        {
          id: 'service',
          label: '服务商',
          configured: true,
          models: [{ id: 'first', efforts: [], initial_effort: 'default' }],
        },
      ];
    if (String(path).endsWith('/refresh'))
      return {
        id: 'service',
        label: '服务商',
        configured: true,
        models: [
          { id: 'first', efforts: [] },
          { id: 'second', efforts: ['low', 'medium', 'high'], initial_effort: 'medium' },
        ],
      };
    return { profile_id: 'service', model: 'first', effort: 'default', efforts: [], configured: true };
  });
  render(<ModelPicker conversationId={null} disabled={false} onChange={onChange} onSettings={vi.fn()} />);
  const trigger = await screen.findByRole('combobox', { name: '当前会话模型' });
  await waitFor(() => expect(trigger).toHaveTextContent('first'));
  fireEvent.click(trigger);
  fireEvent.click(await screen.findByRole('option', { name: 'second' }));
  expect(await screen.findByRole('radio', { name: 'Medium' })).toBeChecked();
  expect(screen.queryByText('默认', { exact: true })).toBeNull();
  expect(onChange).toHaveBeenLastCalledWith({ profile_id: 'service', model: 'second', effort: 'medium' });
});

it.each([
  { efforts: ['off', 'on'], effort: 'on', labels: ['Off', 'On'] },
  { efforts: [], effort: 'default', labels: [] },
])('only shows supported reasoning controls: $labels', async ({ efforts, effort, labels }) => {
  vi.mocked(request).mockImplementation(async (path) => {
    const group = { id: 'service', label: '服务商', configured: true, models: [{ id: 'model', efforts }] };
    if (path === '/model-options') return [group];
    if (String(path).endsWith('/refresh')) return group;
    return { profile_id: 'service', model: 'model', configured: true, effort, efforts };
  });
  render(<ModelPicker conversationId={null} disabled={false} onChange={vi.fn()} onSettings={vi.fn()} />);
  const trigger = await screen.findByRole('combobox', { name: '当前会话模型' });
  await waitFor(() => expect(trigger).toHaveTextContent('model'));
  fireEvent.click(trigger);
  expect(screen.queryAllByRole('radio').map((radio) => radio.parentElement?.textContent)).toEqual(labels);
  expect(screen.queryByText('默认', { exact: true })).toBeNull();
});
