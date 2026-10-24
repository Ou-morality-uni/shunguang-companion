import { useCallback, useEffect, useRef, useState } from 'react';
import type { AnnotationSubmission } from './Annotations';
import {
  request,
  streamChat,
  type Conversation,
  type Message,
  type ModelChoice,
  type Source,
  type ToolEvent,
} from './api';

/** Server owns durable turns; this hook owns selection and transient stream display. */
export function useConversation(
  onComplete: (message: Message) => void,
  speech?: {
    start: () => void;
    delta: (text: string) => void;
    cancel: () => void;
  },
) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState('');
  const [partial, setPartial] = useState<string | null>(null);
  const [currentTools, setCurrentTools] = useState<ToolEvent[]>([]);
  const [currentSources, setCurrentSources] = useState<Source[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const busyRef = useRef(false);
  const stopRequestedRef = useRef(false);
  const activeRef = useRef<string | null>(null);
  const completeRef = useRef(onComplete);
  completeRef.current = onComplete;
  const speechRef = useRef(speech);
  speechRef.current = speech;

  const refreshConversations = useCallback(async () => {
    setConversations(await request<Conversation[]>('/conversations'));
  }, []);

  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => {
    if (busyRef.current) return;
    let live = true;
    setHistoryLoading(true);
    if (!active) {
      setMessages([]);
      setHistoryLoading(false);
      return;
    }
    request<Message[]>(`/conversations/${active}/messages`)
      .then((records) => {
        if (live) setMessages(records);
      })
      .catch(() => {
        if (live) setError('无法读取这段对话，请重试。');
      })
      .finally(() => {
        if (live) setHistoryLoading(false);
      });
    return () => {
      live = false;
    };
  }, [active]);

  function selectConversation(id: string | null) {
    if (busyRef.current || historyLoading) return;
    if (id === activeRef.current) return;
    speechRef.current?.cancel();
    activeRef.current = id;
    setActive(id);
    setMessages([]);
    setError('');
  }

  async function deleteConversation(id: string) {
    if (busyRef.current) return;
    await request<void>(`/conversations/${id}`, { method: 'DELETE' });
    if (activeRef.current === id) selectConversation(null);
    await refreshConversations();
  }

  async function stopReply() {
    stopRequestedRef.current = true;
    speechRef.current?.cancel();
    const id = activeRef.current;
    if (!id) return;
    try {
      // A successful stop means the final record is committed. No synthetic history or polling.
      await request(`/chat/${id}/stop`, { method: 'POST' });
    } catch (failure) {
      setError((failure as Error).message);
      abortRef.current?.abort();
    }
  }

  async function send(
    text: string,
    attachments: string[] = [],
    modelChoice?: ModelChoice,
    annotations?: AnnotationSubmission,
  ) {
    text = text.trim();
    if (!text || busyRef.current || historyLoading) return false;
    busyRef.current = true;
    stopRequestedRef.current = false;
    speechRef.current?.start();
    setBusy(true);
    setError('');
    setPartial('');
    setCurrentTools([]);
    setCurrentSources([]);
    const controller = new AbortController();
    abortRef.current = controller;
    let id = activeRef.current,
      accepted = false,
      accumulated = '',
      completed = false;
    try {
      await streamChat(
        id,
        text,
        controller.signal,
        (kind, data) => {
          if (kind === 'user') {
            const message = data as unknown as Message;
            if (!message.conversation_id) throw new Error('服务没有返回对话标识。');
            accepted = true;
            id = message.conversation_id;
            activeRef.current = id;
            setActive(id);
            setMessages((items) => [...items, message]);
            if (stopRequestedRef.current) void stopReply();
          }
          if (kind === 'delta') {
            accumulated += String(data.text);
            setPartial(accumulated);
            if (!stopRequestedRef.current) speechRef.current?.delta(String(data.text));
          }
          if (kind === 'sources')
            setCurrentSources(Array.isArray(data.sources) ? (data.sources as Source[]) : []);
          if (kind === 'tool')
            setCurrentTools((items) => {
              const next = data as ToolEvent;
              const index = next.id ? items.findIndex((item) => item.id === next.id) : -1;
              return index < 0 ? [...items, next] : items.map((item, i) => (i === index ? next : item));
            });
          if (kind === 'done') {
            const message = data as unknown as Message;
            setMessages((items) => [...items, message]);
            setPartial(null);
            if (message.status === 'complete' && !stopRequestedRef.current) {
              completed = true;
              completeRef.current(message);
            } else speechRef.current?.cancel();
          }
          if (kind === 'error') {
            speechRef.current?.cancel();
            setError(String(data.message));
            setPartial(null);
            if (data.record) setMessages((items) => [...items, data.record as Message]);
          }
        },
        attachments,
        modelChoice,
        annotations,
      );
    } catch (failure) {
      if ((failure as Error).name !== 'AbortError') setError((failure as Error).message);
    } finally {
      if (!completed) speechRef.current?.cancel();
      abortRef.current = null;
      setPartial(null);
      if (id && accepted) {
        try {
          setMessages(await request<Message[]>(`/conversations/${id}/messages`));
        } catch {
          /* Preserve the confirmed visible transcript while offline. */
        }
      }
      try {
        await refreshConversations();
      } catch {
        /* A list failure must not erase a turn. */
      }
      busyRef.current = false;
      setBusy(false);
    }
    return accepted;
  }

  return {
    conversations,
    active,
    messages,
    busy,
    historyLoading,
    error,
    setError,
    partial,
    currentTools,
    currentSources,
    abortRef,
    refreshConversations,
    selectConversation,
    deleteConversation,
    stopReply,
    send,
  };
}
