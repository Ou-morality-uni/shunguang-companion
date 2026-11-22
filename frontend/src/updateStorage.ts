const fallback = new Map<string, string>();

export function updateValue(key: string, value?: string | null) {
  if (value === null) fallback.delete(key);
  else if (value !== undefined) fallback.set(key, value);
  try {
    const storage = key === 'update.channel' ? localStorage : sessionStorage;
    if (value === null) storage.removeItem(key);
    else if (value !== undefined) storage.setItem(key, value);
    return storage.getItem(key);
  } catch {
    return fallback.get(key) ?? null;
  }
}
