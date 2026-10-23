import { useEffect, useRef } from 'react';
import { request, type FileTask } from './api';
import type { AudioController } from './useAudioQueue';

type WorkEvent = { seq: number; task_id: string; kind: string; text: string; created_at: string };

/** Start at the server cursor. Historical tasks never replay speech on reload. */
export function useWorkEvents(enabled: boolean, audio: AudioController, chatBusy = false) {
  const audioRef = useRef(audio);
  audioRef.current = audio;
  const chatBusyRef = useRef(chatBusy);
  chatBusyRef.current = chatBusy;
  useEffect(() => {
    if (!enabled) return;
    const abort = new AbortController();
    const summaries = new Map<string, WorkEvent>();
    let cursor: number | null = null,
      running = false,
      denied = false;
    async function poll() {
      if (running || denied || abort.signal.aborted || document.hidden) return;
      running = true;
      try {
        const result = await request<{ cursor: number; events: WorkEvent[] }>(
          '/work/events' + (cursor === null ? '' : `?after=${cursor}`),
          { signal: abort.signal },
        );
        if (abort.signal.aborted) return;
        const current = cursor;
        cursor = result.cursor;
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
          if (
            ['complete', 'partial'].includes(event.kind) &&
            Date.now() - new Date(event.created_at).getTime() <= 30000
          )
            summaries.set(event.task_id, event);
          if (['cancelled', 'failed', 'restored'].includes(event.kind)) summaries.delete(event.task_id);
        }
        for (const [taskId, event] of summaries) {
          if (!chatBusyRef.current) {
            try {
              const task = await request<FileTask>(`/work/tasks/${taskId}`, { signal: abort.signal });
              if (abort.signal.aborted || chatBusyRef.current || task.status !== 'complete') continue;
              const summary = task.steps.find((step) => step.action === 'summarize')?.result?.summary;
              if (typeof summary === 'string')
                audioRef.current.enqueueWork({ ...event, kind: 'summary', text: summary });
              summaries.delete(taskId);
            } catch {
              /* The task card retains its result if automatic speech is unavailable. */
            }
          }
        }
      } catch (error) {
        if (String((error as Error).message).includes('工作台仅供')) denied = true;
        // Network or speech errors do not cancel work; the next poll can recover.
      } finally {
        running = false;
      }
    }
    void poll();
    const timer = window.setInterval(() => void poll(), 1000);
    return () => {
      abort.abort();
      clearInterval(timer);
    };
  }, [enabled]);
}
