import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { ConversationHistory } from './ConversationHistory';

afterEach(cleanup);

test('moves keyboard focus to delete confirmation and restores it on cancel', () => {
  render(
    <ConversationHistory
      conversations={[{ id: 'one', title: '测试', created_at: '', updated_at: '' }]}
      active="one"
      disabled={false}
      onSelect={vi.fn()}
      onDelete={vi.fn()}
    />,
  );
  const trigger = screen.getByRole('button', { name: '删除对话 测试' });
  trigger.focus();
  fireEvent.click(trigger);
  expect(document.activeElement).toBe(screen.getByRole('button', { name: '确认删除' }));
  fireEvent.click(screen.getByRole('button', { name: '取消' }));
  expect(document.activeElement).toBe(trigger);
});
