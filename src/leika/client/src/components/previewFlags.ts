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
// exactly when the answer has to survive.
//
// A set of the keys that are ON rather than a map to booleans, so what is
// remembered is only what somebody asked for. Going back to the default
// forgets the key instead of writing `false` against it, and a session that
// opens a thousand files carries nothing for the ones it left alone.
//
// Not written to storage. These are ways of looking at something, not
// preferences somebody set: every preference that outlives the tab is one a
// viewer can find and change in the settings popout. Reloading starts plain.

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

/** Open a flag of its own. One call per thing worth remembering. */
export function previewFlag(): PreviewFlag {
  const on = new Set<string>();
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
