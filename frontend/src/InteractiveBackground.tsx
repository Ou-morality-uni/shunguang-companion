import { Component, lazy, Suspense, useCallback, useState, type ReactNode } from 'react';
import type { BackgroundStyle } from './Atmosphere';

const DarkVeil = lazy(() => import('./backgrounds/DarkVeil'));
const GradientBlinds = lazy(() => import('./backgrounds/GradientBlinds'));
const Aurora = lazy(() => import('./backgrounds/Aurora'));

class BackgroundBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

export default function InteractiveBackground({ style }: { style: BackgroundStyle }) {
  const [failed, setFailed] = useState(false);
  const unavailable = useCallback(() => setFailed(true), []);
  if (failed) return null;
  return (
    <BackgroundBoundary>
      <Suspense fallback={null}>
        {style === 'dark-veil' ? (
          <DarkVeil
            color="#ce815d"
            speed={0.35}
            brightness={0.8}
            quality={0.4}
            mouseStrength={0.7}
            intro={false}
            onUnavailable={unavailable}
          />
        ) : style === 'gradient-blinds' ? (
          <GradientBlinds
            gradientColors={['#361723', '#b04e59', '#dca76f']}
            lightColor="#f7c993"
            speed={0.35}
            noise={0.06}
            blindCount={12}
            spotlightOpacity={0.65}
            sway={0.2}
            clickEffect="none"
            intro={false}
            onUnavailable={unavailable}
          />
        ) : (
          <Aurora
            colorStops={['#8d394c', '#edbb80', '#ae4c5c']}
            speed={0.35}
            brightness={0.8}
            height={0.7}
            amplitude={0.6}
            intro={false}
            onUnavailable={unavailable}
          />
        )}
      </Suspense>
    </BackgroundBoundary>
  );
}
