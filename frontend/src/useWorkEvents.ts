import { useEffect, useRef } from 'react';
import { request } from './api';
import type { AudioController } from './useAudioQueue';

type WorkEvent = { seq: number; task_id: string; kind: string; text: string; created_at: string };

/** Start at the server cursor. Historical tasks never replay speech on reload. */
export function useWorkEvents(enabled: boolean, audio: AudioController) {
  const audioRef = useRef(audio);
  audioRef.current = audio;
  useEffect(() => {
    if (!enabled) return;
    const abort = new AbortController();
    let cursor: number | null = null,
      running = false,
      denied = false;
    let timer: number | undefined;
    let delay = 1000;
    function schedule() {
      window.clearTimeout(timer);
      if (!abort.signal.aborted && !denied) timer = window.setTimeout(() => void poll(), delay);
    }
    async function poll() {
      if (running || denied || abort.signal.aborted) return;
      if (document.hidden) {
        delay = 15000;
        schedule();
        return;
      }
      window.clearTimeout(timer);
      running = true;
      try {
        const result = await request<{ cursor: number; events: WorkEvent[] }>(
          '/work/events' + (cursor === null ? '' : `?after=${cursor}`),
          { signal: abort.signal },
        );
        if (abort.signal.aborted) return;
        const current = cursor;
        cursor = result.cursor;
        delay = current === null || result.events.length ? 1000 : Math.min(15000, delay * 2);
        if (result.events.length) window.dispatchEvent(new Event('shunguang-work-updated'));
        const terminal = new Set(
          result.events
            .filter((event) =>
              [
                'complete',
                'partial',
                'failed',
                'cancelled',
                'restored',
                'authorization',
                'waiting_limit',
                'waiting_output',
              ].includes(event.kind),
            )
            .map((event) => event.task_id),
        );
        for (const event of result.events) {
          if (current === null || event.seq <= current) continue;
          if (terminal.has(event.task_id) && ['start', 'progress'].includes(event.kind)) continue;
          audioRef.current.enqueueWork(event);
        }
      } catch (error) {
        delay = Math.min(15000, delay * 2);
        if (String((error as Error).message).includes('工作台仅供')) denied = true;
        // Network or speech errors do not cancel work; the next poll can recover.
      } finally {
        running = false;
        schedule();
      }
    }
    void poll();
    const visible = () => {
      if (!document.hidden) {
        delay = 1000;
        void poll();
      }
    };
    document.addEventListener('visibilitychange', visible);
    return () => {
      abort.abort();
      window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [enabled]);
}
