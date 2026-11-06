import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ResourceImage } from './ResourceImage';

afterEach(cleanup);

it('retries an image that failed before server login when authentication succeeds', () => {
  render(<ResourceImage src="/api/resources/character/avatar.png" alt="测试头像" />);
  fireEvent.error(screen.getByRole('img', { name: '测试头像' }));
  expect(screen.getByRole('img', { name: '测试头像，素材待导入' }).tagName).toBe('SPAN');
  fireEvent(window, new Event('shunguang-authenticated'));
  expect(screen.getByRole('img', { name: '测试头像' }).tagName).toBe('IMG');
});
