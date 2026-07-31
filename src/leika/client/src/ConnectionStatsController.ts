// The connection's counters, between the websocket worker and whatever is
// looking at them.
//
// A module singleton rather than viewer state: the worker lives in one effect
// and the popover that reads it is somewhere else entirely, so there is no
// React parent for the two to share. Nothing here is a preference, so nothing
// is stored -- close the page and the session's totals go with it.

import { useMemo } from "react";

import {
  ConnectionCounters,
  ConnectionReading,
  readConnection,
} from "./connectionStats";
import { createStore } from "./store";

interface ConnectionStatsState {
  /** How many components are asking for measurements. The worker pings only
   * while this is above zero, so a connection nobody is inspecting carries no
   * traffic on its behalf. */
  watchers: number;
  latest: ConnectionCounters | null;
  /** The snapshot before `latest`, which is what makes the two rates
   * subtractable. */
  previous: ConnectionCounters | null;
}

const store = createStore<ConnectionStatsState>({
  watchers: 0,
  latest: null,
  previous: null,
});

export const connectionStats = {
  store,
  /** Start measuring, and hand back the function that stops. */
  watch: (): (() => void) => {
    store.set((state) => ({ watchers: state.watchers + 1 }));
    return () =>
      store.set((state) => ({ watchers: Math.max(0, state.watchers - 1) }));
  },
  record: (counters: ConnectionCounters): void => {
    store.set((state) => ({ latest: counters, previous: state.latest }));
  },
  /** Drop everything measured so far, for a connection that is being replaced
   * rather than continuing. */
  forget: (): void => {
    store.set({ latest: null, previous: null });
  },
};

/** Whether anything is currently asking to be measured. */
export function useConnectionWatched(): boolean {
  return store((state) => state.watchers > 0);
}

/** The connection as it stands, or null before the first snapshot lands. */
export function useConnectionReading(): ConnectionReading | null {
  const latest = store((state) => state.latest);
  const previous = store((state) => state.previous);
  return useMemo(
    () => (latest === null ? null : readConnection(latest, previous)),
    [latest, previous],
  );
}
