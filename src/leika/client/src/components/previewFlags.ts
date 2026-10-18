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
// exactly when the answer has to survive, and browser storage carries it
// across a reload.
//
// The keys that are ON rather than a map to booleans, so what is remembered
// is only what somebody asked for: going back to the default forgets the key.

import * as React from "react";

import {
  persisted,
  type Persisted,
  type PersistedStorage,
} from "../utils/persisted";

export type PreviewFlag = Persisted<readonly string[]>;

/** Open a persistent flag of its own. One call per thing worth remembering. */
export function previewFlag(
  storageKey: string,
  storage?: PersistedStorage | null,
): PreviewFlag {
  return persisted(
    storageKey,
    (stored): readonly string[] =>
      Array.isArray(stored)
        ? stored.filter((key): key is string => typeof key === "string")
        : [],
    storage,
  );
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
  const isOn = () => flag.get().includes(key);
  const value = React.useSyncExternalStore(flag.subscribe, isOn, isOn);
  const set = React.useCallback(
    (next: boolean) => {
      const keys = flag.get();
      if (next === keys.includes(key)) return;
      flag.set(next ? [...keys, key] : keys.filter((other) => other !== key));
    },
    [flag, key],
  );
  return [value, set];
}
