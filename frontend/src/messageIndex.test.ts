import { expect, test } from 'vitest';
import { indexMessages } from './messageIndex';

test('attaches file work only to the first assistant reply after its user request', () => {
  const index = indexMessages([
    { id: 'u', role: 'user', attachments: [{ id: 'file' }] },
    { id: 'a', role: 'assistant' },
    { id: 'b', role: 'assistant' },
  ]);
  expect(index.get('a')?.requestId).toBe('u');
  expect(index.get('a')?.attachments).toEqual([{ id: 'file' }]);
  expect(index.get('b')?.requestId).toBeUndefined();
});
