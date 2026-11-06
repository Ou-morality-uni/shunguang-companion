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

async function updatesAfter(id: string, after?: number | null) {
  const records: Message[] = [];
  let cursor = after ?? 0;
  for (;;) {
    const page = await request<Message[]>(
      `/conversations/${id}/messages${cursor > 0 ? `?after=${cursor}` : ''}`,
    );
    records.push(...page);
    const next = page.at(-1)?.seq;
    if (page.length < 200 || !next || next <= cursor) return records;
    cursor = next;
  }
}

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
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const [hasEarlier, setHasEarlier] = useState(false);
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const earlierRequest = useRef(false);
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
  const historyRequest = useRef(0);
  const completeRef = useRef(onComplete);
  completeRef.current = onComplete;
  const speechRef = useRef(speech);
  speechRef.current = speech;

  const refreshConversations = useCallback(async () => {
    setConversations(await request<Conversation[]>('/conversations'));
  }, []);

  const refreshMessages = useCallback(async () => {
    const id = activeRef.current;
    if (!id || busyRef.current) return false;
    const ticket = ++historyRequest.current;
    const seq = [...messagesRef.current].reverse().find((item) => item.seq)?.seq;
    const records = await updatesAfter(id, seq ? seq - 1 : undefined);
    if (activeRef.current !== id || busyRef.current || ticket !== historyRequest.current) return false;
    setMessages((items) => [...new Map([...items, ...records].map((item) => [item.id, item])).values()]);
    return true;
  }, []);

  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => {
    if (busyRef.current) return;
    let live = true;
    const ticket = ++historyRequest.current;
    setHistoryLoading(true);
    if (!active) {
      setMessages([]);
      setHistoryLoading(false);
      return;
    }
    request<Message[]>(`/conversations/${active}/messages`)
      .then((records) => {
        if (live && ticket === historyRequest.current) setMessages(records);
        if (live && ticket === historyRequest.current) setHasEarlier(records.length === 200);
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

  async function loadEarlier() {
    const id = activeRef.current;
    const before = messagesRef.current[0]?.seq;
    if (!id || !before || busyRef.current || earlierRequest.current) return;
    earlierRequest.current = true;
    setLoadingEarlier(true);
    try {
      const records = await request<Message[]>(`/conversations/${id}/messages?before=${before}`);
      if (activeRef.current !== id) return;
      setMessages((items) => [...new Map([...records, ...items].map((item) => [item.id, item])).values()]);
      setHasEarlier(records.length === 200);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      earlierRequest.current = false;
      setLoadingEarlier(false);
    }
  }

  function selectConversation(id: string | null) {
    if (busyRef.current || historyLoading) return;
    if (id === activeRef.current) return;
    speechRef.current?.cancel();
    historyRequest.current++;
    activeRef.current = id;
    setActive(id);
    setMessages([]);
    setHasEarlier(false);
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
    const syncAfter = [...messagesRef.current].reverse().find((item) => item.seq)?.seq;
    busyRef.current = true;
    historyRequest.current++;
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
          const records = await updatesAfter(id, syncAfter);
          setMessages((items) => [
            ...new Map([...items, ...records].map((item) => [item.id, item])).values(),
          ]);
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
    hasEarlier,
    loadingEarlier,
    loadEarlier,
    busy,
    historyLoading,
    error,
    setError,
    partial,
    currentTools,
    currentSources,
    abortRef,
    refreshConversations,
    refreshMessages,
    selectConversation,
    deleteConversation,
    stopReply,
    send,
  };
}
