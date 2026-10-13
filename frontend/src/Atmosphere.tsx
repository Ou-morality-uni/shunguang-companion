import { FluidBackground } from './FluidBackground';

export function Atmosphere({ enabled }: { enabled: boolean }) {
  return <div className="atmosphere" aria-hidden="true"><div className="ambient-glow glow-rose" /><div className="ambient-glow glow-gold" /><div className="ambient-glow glow-crimson" /><div className="ambient-grid" /><FluidBackground enabled={enabled} /></div>;
}
/** Original ornamental fan, drawn in code rather than using an unverified character portrait. */
export function DawnFan() {
  return <svg viewBox="0 0 320 260" className="dawn-fan" aria-hidden="true">
    <defs><linearGradient id="fan-red" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#f29291" /><stop offset=".45" stopColor="#b83950" /><stop offset="1" stopColor="#571627" /></linearGradient><linearGradient id="fan-gold" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#ffdda6" /><stop offset="1" stopColor="#b47c53" /></linearGradient></defs>
    <circle cx="160" cy="117" r="94" fill="none" stroke="#e9ba8733" /><circle cx="160" cy="117" r="105" fill="none" stroke="#e9ba8718" strokeDasharray="2 9" />
    <path d="M160 220 L23 100 Q160 -26 297 100 Z" fill="url(#fan-red)" stroke="url(#fan-gold)" strokeWidth="1.3" />
    <path d="M160 220 L39 100 Q160 -6 281 100 Z" fill="none" stroke="#f6cf9a66" />
    <defs><clipPath id="fan-clip"><path d="M160 220 L23 100 Q160 -26 297 100 Z" /></clipPath></defs>
    <g clipPath="url(#fan-clip)">{[-64,-48,-32,-16,0,16,32,48,64].map(angle => <path key={angle} d="M160 219 L160 0" transform={`rotate(${angle} 160 220)`} stroke="#f4d5a25c" strokeWidth="1" />)}</g>
    <path d="M37 104 Q160 -8 283 104" fill="none" stroke="#f9d7ad" strokeWidth="3" />
    <g fill="none" stroke="#f7d4ad" strokeWidth="1.5" strokeLinecap="round"><path d="M85 117q12-18 24 0t24 0q12-18 24 0" /><path d="M147 88q12-16 24 0t24 0q12-16 24 0" /><path d="M189 142q10-15 20 0t20 0" /></g>
    <g fill="#fbd9b5"><path d="M104 75l3 7 7 3-7 3-3 7-3-7-7-3 7-3z" /><path d="M226 113l2 5 5 2-5 2-2 5-2-5-5-2 5-2z" /></g>
    <circle cx="160" cy="220" r="5" fill="url(#fan-gold)" /><path d="M160 224v20m0-4q-13 9-6 17m6-17q13 9 6 17" stroke="#ecc18c" fill="none" strokeWidth="2" />
  </svg>;
}

export function VoiceWave({ playing = false }: { playing?: boolean }) {
  return <div className={`voice-wave ${playing ? 'playing' : ''}`} aria-hidden="true">{Array.from({ length: 31 }, (_, index) => <i key={index} style={{ height: `${8 + Math.sin(index * .79) ** 2 * 28}px`, animationDelay: `${index * -.11}s` }} />)}</div>;
}
