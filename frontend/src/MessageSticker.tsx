import { useState } from 'react';
import type { Sticker } from './api';

const fallbackImages = [
  ['49-red-daily-by-your-side.png', '在呢，陪着你'],
  ['33-red-daily-sit-together.png', '陪你坐会儿'],
  ['22-red-daily-listening.png', '你说，我听着'],
];
const resource = '/api/resources/character/stickers/';

/** One decoration, kept separate from copied/spoken text, with bounded local fallbacks. */
export function MessageSticker({ sticker }: { sticker: Sticker }) {
  const [failed, setFailed] = useState<string[]>([]);
  const candidates = [
    ...(sticker.url.startsWith(resource) && /^[a-zA-Z0-9-]+\.png$/.test(sticker.url.slice(resource.length))
      ? [[sticker.url, sticker.caption]]
      : []),
    ...fallbackImages.map(([file, caption]) => [resource + file, caption]),
  ];
  const selected = candidates.find(([url]) => !failed.includes(url));
  return (
    <div className="message-sticker">
      {selected ? (
        <img
          src={selected[0]}
          alt={`叶瞬光：${selected[1]}`}
          width={160}
          height={160}
          loading="lazy"
          decoding="async"
          onError={() => setFailed((items) => [...items, selected[0]])}
        />
      ) : (
        <span className="sticker-fallback">在呢，陪着你。</span>
      )}
    </div>
  );
}
