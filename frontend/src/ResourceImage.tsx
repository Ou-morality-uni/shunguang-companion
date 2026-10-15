import { useEffect, useState } from 'react';
import { Flower2 } from 'lucide-react';

/** Missing optional media never replaces the designated avatar with another portrait. */
export function ResourceImage({
  src,
  alt,
  className = '',
  label = false,
}: {
  src: string;
  alt: string;
  className?: string;
  label?: boolean;
}) {
  const [missing, setMissing] = useState(false);
  useEffect(() => setMissing(false), [src]);
  return missing ? (
    <span className={`${className} media-fallback`} role="img" aria-label={`${alt}，素材待导入`}>
      <Flower2 size={26} strokeWidth={1.2} />
      {label && <small>素材待导入</small>}
    </span>
  ) : (
    <img
      src={src}
      alt={alt}
      className={className}
      onError={() => setMissing(true)}
      loading={className === 'welcome-avatar' ? 'eager' : 'lazy'}
    />
  );
}
