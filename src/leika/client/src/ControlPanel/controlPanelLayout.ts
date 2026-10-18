// Where the control panel sits, owned by one viewer and remembered per server
// and workspace.
//
// Until the viewer moves, resizes, or collapses the panel, it follows the
// theme's `control_layout`, including a change mid-session. After that the
// browser keeps the viewer's arrangement for this workspace, and it wins over
// the theme until the viewer resets it with a double-click on the header.

import React from "react";

import { parseBoundedPersistedJson } from "../persistenceLimits";
import { createStore, type Store } from "../store";
import { useViewer } from "../ViewerContext";
import type { ThemeConfigurationMessage } from "../WebsocketMessages";
import {
  CONTROL_WIDTH_PX,
  MAX_CONTROL_WIDTH_PX,
  MIN_CONTROL_WIDTH_PX,
} from "./controlWidth";

export type ControlPlacement = ThemeConfigurationMessage["control_layout"];

export interface ControlPanelLayout {
  placement: ControlPlacement;
  /** Floating position: the panel's distance from the canvas's right and top
   * edges, so a panel left where it starts stays in that corner. */
  right: number;
  top: number;
  width: number;
  /** The one collapsed state, shared by the desktop panel and the phone's
   * bottom sheet. */
  collapsed: boolean;
}

/** The gap a floating panel keeps from the canvas edges it starts against. */
export const FLOATING_INSET_PX = 15;

const STORAGE_KEY_PREFIX = "leika.control-panel:";

export interface ControlPanelStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function browserStorage(): ControlPanelStorage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function configuredLayout(placement: ControlPlacement): ControlPanelLayout {
  return {
    placement,
    right: FLOATING_INSET_PX,
    top: FLOATING_INSET_PX,
    width: CONTROL_WIDTH_PX,
    collapsed: false,
  };
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** A saved arrangement, or null for none or for anything that is not one. */
export function readControlPanelLayout(
  storage: ControlPanelStorage | null,
  key: string,
): ControlPanelLayout | null {
  let value: unknown;
  try {
    const serialized = storage?.getItem(key);
    if (serialized == null) return null;
    value = parseBoundedPersistedJson(serialized);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) return null;
  const { placement, right, top, width, collapsed } = value as Record<
    string,
    unknown
  >;
  if (
    (placement !== "floating" &&
      placement !== "left" &&
      placement !== "right") ||
    !isFiniteNumber(right) ||
    !isFiniteNumber(top) ||
    !isFiniteNumber(width) ||
    typeof collapsed !== "boolean"
  ) {
    return null;
  }
  return {
    placement,
    right,
    top,
    width: Math.min(
      MAX_CONTROL_WIDTH_PX,
      Math.max(MIN_CONTROL_WIDTH_PX, width),
    ),
    collapsed,
  };
}

export interface ControlPanelSession {
  store: Store<ControlPanelLayout>;
  /** Point the session at the server's workspace (null until it is named)
   * and the theme's starting placement. */
  sync(
    server: string,
    workspaceId: string | null,
    configured: ControlPlacement,
  ): void;
  /** Show a change without remembering it: a gesture still in progress. */
  preview(change: Partial<ControlPanelLayout>): void;
  /** Apply a change and remember the arrangement for this workspace. */
  save(change?: Partial<ControlPanelLayout>): void;
  /** Forget the arrangement and follow the theme again. */
  reset(): void;
}

export function createControlPanelSession(
  storage: ControlPanelStorage | null = browserStorage(),
): ControlPanelSession {
  const store = createStore(configuredLayout("floating"));
  let key: string | null = null;
  let configured: ControlPlacement = "floating";
  let arranged = false;

  return {
    store,
    sync(server, workspaceId, nextConfigured) {
      const nextKey =
        workspaceId === null
          ? null
          : `${STORAGE_KEY_PREFIX}${server}:${workspaceId}`;
      const configuredChanged = nextConfigured !== configured;
      configured = nextConfigured;
      // A reconnect clears the workspace until the server names it again;
      // the panel stays where it is meanwhile, and nothing is saved.
      if (nextKey !== null && nextKey !== key) {
        const saved = readControlPanelLayout(storage, nextKey);
        arranged = saved !== null;
        store.set(saved ?? configuredLayout(configured));
      } else if (configuredChanged && !arranged) {
        store.set(configuredLayout(configured));
      }
      key = nextKey;
    },
    preview: (change) => store.set(change),
    save(change = {}) {
      store.set(change);
      arranged = true;
      if (key === null) return;
      try {
        storage?.setItem(key, JSON.stringify(store.get()));
      } catch {
        // A full or read-only store leaves the panel usable for this session.
      }
    },
    reset() {
      arranged = false;
      store.set(configuredLayout(configured));
      if (key === null) return;
      try {
        storage?.removeItem(key);
      } catch {
        // As above: forgetting is best-effort.
      }
    },
  };
}

export const ControlPanelContext =
  React.createContext<ControlPanelSession | null>(null);

/** The viewer's control-panel session, for the app root to provide. */
export function useControlPanelSession(): ControlPanelSession {
  const viewer = useViewer();
  const server = viewer.server;
  const workspaceId = viewer.useGui((state) => state.workspaceId);
  const configured = viewer.useGui((state) => state.theme.control_layout);
  const [session] = React.useState(() => createControlPanelSession());
  React.useLayoutEffect(
    () => session.sync(server, workspaceId, configured),
    [session, server, workspaceId, configured],
  );
  return session;
}

export function useControlPanel(): ControlPanelSession {
  const session = React.useContext(ControlPanelContext);
  if (session === null) {
    throw new Error("useControlPanel must be used within ControlPanelContext");
  }
  return session;
}

/** The width the desktop panel takes from the canvas at `edge`: its own width
 * while it is docked there and expanded, and nothing otherwise. */
export function useCanvasInset(
  edge: "left" | "right",
  mobile: boolean,
): number {
  return useControlPanel().store((layout) =>
    !mobile && layout.placement === edge && !layout.collapsed
      ? layout.width
      : 0,
  );
}
