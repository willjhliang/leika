import { useCallback, useRef, useSyncExternalStore } from "react";

// ---------------------------------------------------------------------------
// createStore<T> -- simple reactive store
// ---------------------------------------------------------------------------

type Listener = () => void;
type SetArg<T> = Partial<T> | ((prev: T) => Partial<T>);

export interface Store<T> {
  /** React hook: subscribe to the full state or a selected slice. */
  (): T;
  <U>(selector: (state: T) => U, equalityFn?: (a: U, b: U) => boolean): U;

  /** Read current state (non-reactive). */
  get: () => T;
  /** Merge partial state or apply an updater. */
  set: (arg: SetArg<T>) => void;
  /** Subscribe to any state change. Returns unsubscribe function. */
  subscribe: (listener: Listener) => () => void;
}

export function createStore<T extends object>(initialState: T): Store<T> {
  let state = initialState;
  const listeners = new Set<Listener>();

  function get(): T {
    return state;
  }

  function set(arg: SetArg<T>): void {
    const partial = typeof arg === "function" ? arg(state) : arg;
    // Skip notify if nothing changed.
    const keys = Object.keys(partial) as (keyof T)[];
    if (keys.every((k) => Object.is(state[k], (partial as T)[k]))) return;
    state = { ...state, ...partial };
    listeners.forEach((l) => l());
  }

  function subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }

  // The callable hook with overloads.
  function useStore(): T;
  function useStore<U>(
    selector: (s: T) => U,
    equalityFn?: (a: U, b: U) => boolean,
  ): U;
  function useStore<U>(
    selector?: (s: T) => U,
    equalityFn?: (a: U, b: U) => boolean,
  ): T | U {
    // Cache the last selected value to avoid unnecessary re-renders when
    // the selector returns a structurally-equal result.
    const cache = useRef<{
      value: U;
      state: T | undefined;
      selector: typeof selector;
      equalityFn: typeof equalityFn;
      initialized: boolean;
    }>({
      value: undefined as U,
      state: undefined,
      selector: undefined,
      equalityFn: undefined,
      initialized: false,
    });

    const getSnapshot = () => {
      if (!selector) return state as T | U;
      const previous = cache.current;
      // React may read a snapshot repeatedly without a store update. Even a
      // selector that allocates an object must return the same snapshot for
      // identical inputs, or useSyncExternalStore can render indefinitely.
      if (
        previous.initialized &&
        previous.state === state &&
        previous.selector === selector &&
        previous.equalityFn === equalityFn
      )
        return previous.value;

      const next = selector(state);
      const value =
        previous.initialized && (equalityFn ?? Object.is)(previous.value, next)
          ? previous.value
          : next;
      cache.current = { value, state, selector, equalityFn, initialized: true };
      return value;
    };
    return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  }

  useStore.get = get;
  useStore.set = set;
  useStore.subscribe = subscribe;

  return useStore as Store<T>;
}

// ---------------------------------------------------------------------------
// createKeyedStore<V> -- per-key subscription store
// ---------------------------------------------------------------------------

export interface KeyedStore<V> {
  /** React hook: subscribe to a single key, optionally with selector. */
  (key: string): V | undefined;
  <U>(
    key: string,
    selector: (val: V | undefined) => U,
    equalityFn?: (a: U, b: U) => boolean,
  ): U;

  /** Read one key (non-reactive). */
  get: (key: string) => V | undefined;
  /**
   * Batch-set entries. Keys mapped to undefined are deleted.
   * Only listeners for affected keys are notified.
   */
  set: (updates: Record<string, V | undefined>) => void;
  /** Delete every entry. */
  clear: () => void;
  /** Subscribe to changes for a specific key. Returns unsubscribe. */
  subscribe: (key: string, listener: Listener) => () => void;
}

export function createKeyedStore<V>(): KeyedStore<V> {
  const map = new Map<string, V>();
  // Per-key listeners.
  const keyListeners = new Map<string, Set<Listener>>();
  // Per-key version counters (bumped on every change to that key).
  const keyVersions = new Map<string, number>();

  function getVersion(key: string): number {
    return keyVersions.get(key) ?? 0;
  }

  function bumpVersion(key: string): void {
    keyVersions.set(key, getVersion(key) + 1);
  }

  function reclaimVersion(key: string): void {
    if (!map.has(key) && !keyListeners.has(key)) keyVersions.delete(key);
  }

  function notifyKey(key: string): void {
    const set = keyListeners.get(key);
    if (set) set.forEach((l) => l());
  }

  function get(key: string): V | undefined {
    return map.get(key);
  }

  function set(updates: Record<string, V | undefined>): void {
    const changedKeys: string[] = [];

    for (const key of Object.keys(updates)) {
      const value = updates[key];
      if (value === undefined) {
        if (map.has(key)) {
          map.delete(key);
          bumpVersion(key);
          changedKeys.push(key);
        }
      } else {
        const prev = map.get(key);
        if (!Object.is(prev, value)) {
          map.set(key, value);
          bumpVersion(key);
          changedKeys.push(key);
        }
      }
    }

    // Notify only affected keys.
    for (const key of changedKeys) {
      notifyKey(key);
      reclaimVersion(key);
    }
  }

  function clear(): void {
    const keys = [...map.keys()];
    map.clear();
    for (const key of keys) {
      bumpVersion(key);
      notifyKey(key);
      reclaimVersion(key);
    }
  }

  function subscribeToKey(key: string, listener: Listener): () => void {
    if (!keyListeners.has(key)) {
      keyListeners.set(key, new Set());
    }
    keyListeners.get(key)!.add(listener);
    return () => {
      const s = keyListeners.get(key);
      if (s) {
        s.delete(listener);
        if (s.size === 0) {
          keyListeners.delete(key);
          reclaimVersion(key);
        }
      }
    };
  }

  // The callable hook with overloads.
  function useKeyedStore(key: string): V | undefined;
  function useKeyedStore<U>(
    key: string,
    selector: (val: V | undefined) => U,
    equalityFn?: (a: U, b: U) => boolean,
  ): U;
  function useKeyedStore<U>(
    key: string,
    selector?: (val: V | undefined) => U,
    equalityFn?: (a: U, b: U) => boolean,
  ): V | undefined | U {
    const cache = useRef<{
      value: V | undefined | U;
      version: number;
      key: string;
      selector: ((val: V | undefined) => U) | undefined;
      equalityFn: ((a: U, b: U) => boolean) | undefined;
    }>({
      value: undefined,
      version: -1,
      key: "",
      selector: undefined,
      equalityFn: undefined,
    });

    // New subscribe identity when key changes, so useSyncExternalStore
    // re-subscribes to the correct key.
    const subscribe = useCallback(
      (listener: Listener) => subscribeToKey(key, listener),
      [key],
    );

    const getSnapshot = () => {
      const version = getVersion(key);
      const selectionChanged =
        cache.current.selector !== selector ||
        cache.current.equalityFn !== equalityFn;
      // The selected value can change even while the key and its data do not:
      // selectors may close over props that changed on a parent render.
      if (
        cache.current.key !== key ||
        cache.current.version !== version ||
        selectionChanged
      ) {
        const raw = map.get(key);
        const next = selector ? selector(raw) : raw;
        if (cache.current.key === key && cache.current.version >= 0) {
          if (
            equalityFn
              ? equalityFn(cache.current.value as U, next as U)
              : Object.is(cache.current.value, next)
          ) {
            cache.current.version = version;
            cache.current.selector = selector;
            cache.current.equalityFn = equalityFn;
            return cache.current.value as V | undefined | U;
          }
        }
        cache.current = {
          value: next,
          version,
          key,
          selector,
          equalityFn,
        };
        return next;
      }
      return cache.current.value as V | undefined | U;
    };
    const value = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

    return value;
  }

  useKeyedStore.get = get;
  useKeyedStore.set = set;
  useKeyedStore.clear = clear;
  useKeyedStore.subscribe = subscribeToKey;

  return useKeyedStore as KeyedStore<V>;
}
