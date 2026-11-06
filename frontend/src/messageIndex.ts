export function indexMessages<T extends { id: string; role: string; attachments?: unknown[] }>(
  messages: T[],
) {
  const result = new Map<string, { record: T; requestId?: string; attachments: T['attachments'] }>();
  let user: T | undefined;
  let answered = false;
  for (const record of messages) {
    if (record.role === 'user') {
      user = record;
      answered = false;
    }
    result.set(record.id, {
      record,
      requestId: record.role === 'assistant' && !answered ? user?.id : undefined,
      attachments: user?.attachments,
    });
    if (record.role === 'assistant') answered = true;
  }
  return result;
}
