// A yes or no that a preview remembers about how it is being looked at.
//
// Per preview, not per session. Filling the window, or standing a contents
// list up beside a document, is a decision about one thing being harder to
// read than it opened -- a dense figure, a long README -- and the next file
// is a different thing. So each flag is keyed by whatever is being
// previewed, and pressing a toggle on one says nothing about any other.
//
// Held outside React because it outlives every component that reads it: the
// preview a flag belongs to is unmounted the moment it closes, which is
// exactly when the answer has to survive. The set is restored from browser
// storage as the module starts, so the same answer also survives a reload.
//
// A set of the keys that are ON rather than a map to booleans, so what is
// remembered is only what somebody asked for. Going back to the default
// forgets the key instead of writing `false` against it, and a session that
// opens a thousand files carries nothing for the ones it left alone.
//
// Written as one small array per kind of flag. Keeping the two flags apart
// lets each owner update its answer without reading, merging, and possibly
// overwriting the other owner's newer answer.

import * as React from "react";

/** One remembered flag: where to read it, and how to set it. */
export interface PreviewFlag {
  /** The `useSyncExternalStore` half, held apart from the hook so that the
   * flag can be read without a component to read it from. */
  store: {
    subscribe: (listener: () => void) => () => void;
    snapshot: (key: string) => boolean;
  };
  set: (key: string, next: boolean) => void;
}

export interface PreviewFlagStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function browserStorage(): PreviewFlagStorage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function readPreviewFlag(
  storageKey: string,
  storage: PreviewFlagStorage | null,
): Set<string> {
  if (storage === null) return new Set();
  try {
    const raw = storage.getItem(storageKey);
    if (raw === null) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(
      parsed.filter((key): key is string => typeof key === "string"),
    );
  } catch {
    // Storage can be inaccessible, or an older/hand-edited value can be
    // malformed. Neither should stop previews working for this session.
    return new Set();
  }
}

/** Open a persistent flag of its own. One call per thing worth remembering. */
export function previewFlag(
  storageKey: string,
  storage: PreviewFlagStorage | null = browserStorage(),
): PreviewFlag {
  const on = readPreviewFlag(storageKey, storage);
  const listeners = new Set<() => void>();
  return {
    store: {
      subscribe(listener) {
        listeners.add(listener);
        return () => {
          listeners.delete(listener);
        };
      },
      snapshot(key) {
        return on.has(key);
      },
    },
    set(key, next) {
      // Previews mount and unmount constantly, and each one asks. Only a
      // real change is worth waking every reader for.
      if (next === on.has(key)) return;
      if (next) on.add(key);
      else on.delete(key);
      if (storage !== null) {
        try {
          storage.setItem(storageKey, JSON.stringify([...on]));
        } catch {
          // A private/full store still leaves the in-memory flag useful until
          // the page goes away.
        }
      }
      for (const listener of listeners) listener();
    },
  };
}

/** Whether THIS preview has `flag` set, and the way to say otherwise.
 *
 * `key` names what is being previewed, and is what the answer is remembered
 * against. Callers provide a stable identity: a source uuid for a preview
 * button, a pane uuid for viewport media, or a filename fallback for a one-off
 * file. Two views share state only when their caller establishes that identity.
 */
export function usePreviewFlag(
  flag: PreviewFlag,
  key: string,
): [boolean, (next: boolean) => void] {
  const value = React.useSyncExternalStore(
    flag.store.subscribe,
    () => flag.store.snapshot(key),
    () => flag.store.snapshot(key),
  );
  const set = React.useCallback(
    (next: boolean) => flag.set(key, next),
    [flag, key],
  );
  return [value, set];
}
