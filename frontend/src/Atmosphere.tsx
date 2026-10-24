import InteractiveBackground from './InteractiveBackground';

export const backgroundStyles = [
  { id: 'dark-veil', name: 'Dark Veil · 柔光纱幕', description: '柔软光纱随鼠标弯曲，温柔相伴。' },
  {
    id: 'gradient-blinds',
    name: 'Gradient Blinds · 渐变光幕',
    description: '鼠标聚光掠过渐变纹理，互动更鲜明。',
  },
  { id: 'aurora', name: 'Aurora · 暖霞极光', description: '顶部霞光缓缓流动，轻轻追随鼠标。' },
] as const;
export type BackgroundStyle = (typeof backgroundStyles)[number]['id'];

export function Atmosphere({ enabled, style }: { enabled: boolean; style: BackgroundStyle }) {
  return (
    <div className="atmosphere" aria-hidden="true">
      <div className="ambient-glow glow-rose" />
      <div className="ambient-glow glow-gold" />
      <div className="ambient-glow glow-crimson" />
      <svg className="dawn-ribbons" viewBox="0 0 1600 900" preserveAspectRatio="none">
        <defs>
          <linearGradient id="dawn-light" x1="0" y1="0" x2="1" y2="0">
            <stop stopColor="#6b263e" stopOpacity="0" />
            <stop offset=".3" stopColor="#c65a70" stopOpacity=".6" />
            <stop offset=".65" stopColor="#edc08c" stopOpacity=".9" />
            <stop offset="1" stopColor="#b3445e" stopOpacity="0" />
          </linearGradient>
        </defs>
        <g className="dawn-stream dawn-stream-top" fill="none" stroke="url(#dawn-light)">
          <path d="M-150 145 C190 -95 440 225 780 90 S1280 45 1750 175" strokeWidth="2" />
          <path d="M-150 160 C200 -70 430 245 790 112 S1290 58 1750 190" strokeWidth="14" opacity=".13" />
          <path d="M-150 185 C210 -30 460 262 800 135 S1300 80 1750 220" strokeWidth="1" opacity=".65" />
          <path d="M-150 200 C220 -10 470 280 810 158 S1320 98 1750 245" strokeWidth="28" opacity=".05" />
        </g>
        <g className="dawn-stream dawn-stream-bottom" fill="none" stroke="url(#dawn-light)">
          <path d="M-120 770 C290 1010 480 680 900 815 S1370 830 1740 705" strokeWidth="1.5" opacity=".55" />
          <path d="M-120 792 C290 1032 500 704 910 838 S1390 850 1740 730" strokeWidth="18" opacity=".08" />
        </g>
      </svg>
      {enabled && (
        <div className="interactive-background" data-background={style}>
          <InteractiveBackground key={style} style={style} />
        </div>
      )}
    </div>
  );
}
/** Original ornamental fan, drawn in code rather than using an unverified character portrait. */
export function DawnFan() {
  return (
    <svg viewBox="0 0 320 260" className="dawn-fan" aria-hidden="true">
      <defs>
        <linearGradient id="fan-red" x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#f29291" />
          <stop offset=".45" stopColor="#b83950" />
          <stop offset="1" stopColor="#571627" />
        </linearGradient>
        <linearGradient id="fan-gold" x1="0" y1="0" x2="0" y2="1">
          <stop stopColor="#ffdda6" />
          <stop offset="1" stopColor="#b47c53" />
        </linearGradient>
      </defs>
      <circle cx="160" cy="117" r="94" fill="none" stroke="#e9ba8733" />
      <circle cx="160" cy="117" r="105" fill="none" stroke="#e9ba8718" strokeDasharray="2 9" />
      <path
        d="M160 220 L23 100 Q160 -26 297 100 Z"
        fill="url(#fan-red)"
        stroke="url(#fan-gold)"
        strokeWidth="1.3"
      />
      <path d="M160 220 L39 100 Q160 -6 281 100 Z" fill="none" stroke="#f6cf9a66" />
      <defs>
        <clipPath id="fan-clip">
          <path d="M160 220 L23 100 Q160 -26 297 100 Z" />
        </clipPath>
      </defs>
      <g clipPath="url(#fan-clip)">
        {[-64, -48, -32, -16, 0, 16, 32, 48, 64].map((angle) => (
          <path
            key={angle}
            d="M160 219 L160 0"
            transform={`rotate(${angle} 160 220)`}
            stroke="#f4d5a25c"
            strokeWidth="1"
          />
        ))}
      </g>
      <path d="M37 104 Q160 -8 283 104" fill="none" stroke="#f9d7ad" strokeWidth="3" />
      <g fill="none" stroke="#f7d4ad" strokeWidth="1.5" strokeLinecap="round">
        <path d="M85 117q12-18 24 0t24 0q12-18 24 0" />
        <path d="M147 88q12-16 24 0t24 0q12-16 24 0" />
        <path d="M189 142q10-15 20 0t20 0" />
      </g>
      <g fill="#fbd9b5">
        <path d="M104 75l3 7 7 3-7 3-3 7-3-7-7-3 7-3z" />
        <path d="M226 113l2 5 5 2-5 2-2 5-2-5-5-2 5-2z" />
      </g>
      <circle cx="160" cy="220" r="5" fill="url(#fan-gold)" />
      <path d="M160 224v20m0-4q-13 9-6 17m6-17q13 9 6 17" stroke="#ecc18c" fill="none" strokeWidth="2" />
    </svg>
  );
}

export function VoiceWave({ playing = false }: { playing?: boolean }) {
  return (
    <div className={`voice-wave ${playing ? 'playing' : ''}`} aria-hidden="true">
      {Array.from({ length: 31 }, (_, index) => (
        <i
          key={index}
          style={{ height: `${8 + Math.sin(index * 0.79) ** 2 * 28}px`, animationDelay: `${index * -0.11}s` }}
        />
      ))}
    </div>
  );
}
