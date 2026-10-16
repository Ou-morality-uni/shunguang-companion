import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { MessageSticker } from './MessageSticker';
import type { Sticker } from './api';

afterEach(cleanup);

const sticker: Sticker = {
  id: 'red-hug',
  url: '/api/resources/character/stickers/03-red-hug.png',
  caption: '抱抱',
  persona: 'red',
  scene: 'comfort',
};

it('renders exactly one local sticker with a readable caption', () => {
  const { container } = render(<MessageSticker sticker={sticker} />);
  const image = screen.getByRole('img', { name: '叶瞬光：抱抱' });
  expect(image.getAttribute('src')).toBe(sticker.url);
  expect(container.querySelectorAll('img')).toHaveLength(1);
  expect(image.getAttribute('loading')).toBe('lazy');
  expect(container.textContent).toBe('');
});

it('falls back to neutral red images on failure without requesting external paths or looping', () => {
  render(<MessageSticker sticker={{ ...sticker, url: 'https://untrusted.example/image.png' }} />);
  const initial = screen.getByRole('img');
  expect(initial.getAttribute('src')).toContain('49-red-daily-by-your-side.png');
  fireEvent.error(initial);
  expect(screen.getByRole('img').getAttribute('src')).toContain('33-red-daily-sit-together.png');
  fireEvent.error(screen.getByRole('img'));
  expect(screen.getByRole('img').getAttribute('src')).toContain('22-red-daily-listening.png');
  fireEvent.error(screen.getByRole('img'));
  expect(screen.queryByRole('img')).toBeNull();
  expect(screen.getByText('在呢，陪着你。')).toBeTruthy();
});

it('replaces a failed matched image with a neutral image while keeping only one image', () => {
  render(<MessageSticker sticker={sticker} />);
  fireEvent.error(screen.getByRole('img'));
  expect(screen.getAllByRole('img')).toHaveLength(1);
  expect(screen.getByRole('img').getAttribute('alt')).toBe('叶瞬光：在呢，陪着你');
});
