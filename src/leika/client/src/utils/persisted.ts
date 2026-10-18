export interface PersistedStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function browserStorage(): PersistedStorage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** A value remembered in browser storage as JSON and shared by every reader
 * on the page; `parse` turns a stored (or missing) value into a valid one.
 * Blocked or full storage still leaves the value for this page. */
export function persisted<T>(
  storageKey: string,
  parse: (stored: unknown) => T,
  storage: PersistedStorage | null = browserStorage(),
) {
  let current: T;
  try {
    const stored = storage?.getItem(storageKey) ?? null;
    current = parse(stored === null ? undefined : JSON.parse(stored));
  } catch {
    current = parse(undefined);
  }
  const listeners = new Set<() => void>();
  return {
    get: (): T => current,
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    set(next: T): void {
      current = next;
      try {
        storage?.setItem(storageKey, JSON.stringify(next));
      } catch {
        // Kept in memory for this page.
      }
      for (const listener of listeners) listener();
    },
  };
}

export type Persisted<T> = ReturnType<typeof persisted<T>>;
