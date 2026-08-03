import React from "react";

import { ImageFit } from "../ClientSettings";
import { createStore, Store } from "../store";
import {
  VIEWPORT_ROOT_PANE_ID,
  ViewportDropRegion,
  ViewportLayout,
  collectViewportPaneIds,
  equalizeViewportPanes,
  hasViewportPane,
  insertViewportPane,
  normalizeViewportLayout,
  reconcileViewportLayout,
  removeViewportPane,
  sameViewportLayout,
} from "./layoutModel";

export type ViewportPanePlacement = Exclude<ViewportDropRegion, "center">;

export interface ViewportImageProps {
  _data: Uint8Array<ArrayBuffer> | null;
  _format: "jpeg" | "png";
  title: string;
  visible: boolean;
  /** `null` defers to the viewer's own "Image fit" setting. */
  fit: ImageFit | null;
}

export interface ViewportPlotlyProps {
  _plotly_json_str: string;
  /** JSON string with "light"/"dark" template definitions, applied when the
   * figure does not specify a template. */
  _theme_templates: string;
  title: string;
  visible: boolean;
}

export interface ViewportViserProps {
  /** Absolute embed URL, rendered near-verbatim; null for port-based targets. */
  _url: string | null;
  /** Viser server port; the host is derived from the page's hostname. Null
   * for URL-based targets. Exactly one of _url/_port is set. */
  _port: number | null;
  title: string;
  visible: boolean;
}

export interface ViewportRootPane {
  kind: "root";
  paneId: typeof VIEWPORT_ROOT_PANE_ID;
  visible: boolean;
}

export interface ViewportImagePane {
  kind: "image";
  paneId: string;
  props: ViewportImageProps;
}

export interface ViewportPlotlyPane {
  kind: "plotly";
  paneId: string;
  props: ViewportPlotlyProps;
}

export interface ViewportViserPane {
  kind: "viser";
  paneId: string;
  props: ViewportViserProps;
}

/** Server-declared panes that render content other than the 3D hidden root. */
export type ViewportContentPane =
  | ViewportImagePane
  | ViewportPlotlyPane
  | ViewportViserPane;

export type ViewportPane = ViewportRootPane | ViewportContentPane;

export interface ViewportState {
  panes: Record<string, ViewportPane>;
  layout: ViewportLayout;
  interactionEpoch: number;
}

export interface ViewportImageDeclaration {
  pane_id: string;
  props: ViewportImageProps;
  placement: ViewportPanePlacement;
  relative_to: string;
  equalize_group: readonly string[];
}

export interface ViewportPlotlyDeclaration {
  pane_id: string;
  props: ViewportPlotlyProps;
  placement: ViewportPanePlacement;
  relative_to: string;
  equalize_group: readonly string[];
}

export interface ViewportViserDeclaration {
  pane_id: string;
  props: ViewportViserProps;
  placement: ViewportPanePlacement;
  relative_to: string;
  equalize_group: readonly string[];
}

// A union of Partials rather than a Partial of an intersection, so that
// same-named props with different types never collapse across pane kinds.
export type ViewportPaneUpdates =
  | Partial<ViewportImageProps>
  | Partial<ViewportPlotlyProps>
  | Partial<ViewportViserProps>;

export interface ViewportActions {
  /** Clear all temporal pane state, including layout (used by file playback). */
  reset: () => void;
  /** Clear pane contents for a new connection while retaining browser layout. */
  resetPanes: () => void;
  /** Select the websocket server portion of the persistence namespace. */
  setPersistenceServer: (serverUrl: string) => void;
  /** Restore the workspace-specific persisted layout. */
  setPersistenceWorkspace: (workspaceId: string) => void;
  addImagePane: (message: ViewportImageDeclaration) => void;
  addPlotlyPane: (message: ViewportPlotlyDeclaration) => void;
  addViserPane: (message: ViewportViserDeclaration) => void;
  updatePane: (paneId: string, updates: ViewportPaneUpdates) => void;
  removePane: (paneId: string) => void;
  setPaneSnapshot: (paneIds: readonly string[]) => void;
  commitUserLayout: (layout: ViewportLayout) => void;
}

export interface ViewportLayoutStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const STORAGE_KEY_PREFIX = "leika.viewport.layout.v2:";

export function viewportLayoutStorageKey(
  serverUrl: string,
  workspaceId: string,
): string {
  return STORAGE_KEY_PREFIX + serverUrl + ":" + workspaceId;
}

function browserStorage(): ViewportLayoutStorage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function initialLayout(): ViewportLayout {
  return {
    version: 1,
    root: { type: "pane", pane_id: VIEWPORT_ROOT_PANE_ID },
  };
}

function initialPanes(): Record<string, ViewportPane> {
  const panes = Object.create(null) as Record<string, ViewportPane>;
  panes[VIEWPORT_ROOT_PANE_ID] = {
    kind: "root",
    paneId: VIEWPORT_ROOT_PANE_ID,
    visible: true,
  };
  return panes;
}

function initialState(
  layout = initialLayout(),
  interactionEpoch = 0,
): ViewportState {
  return { panes: initialPanes(), layout, interactionEpoch };
}

function copyPaneRecord(
  panes: Record<string, ViewportPane>,
): Record<string, ViewportPane> {
  return Object.assign(
    Object.create(null) as Record<string, ViewportPane>,
    panes,
  );
}

function paneIsVisible(pane: ViewportPane | undefined): boolean {
  return (
    pane === undefined ||
    (pane.kind === "root" ? pane.visible : pane.props.visible)
  );
}

function retainedPaneIds(
  layout: ViewportLayout,
  panes: Record<string, ViewportPane>,
  authoritativePaneIds: ReadonlySet<string> | null,
): string[] {
  return collectViewportPaneIds(layout).filter(
    (paneId) =>
      paneIsVisible(panes[paneId]) &&
      (paneId === VIEWPORT_ROOT_PANE_ID ||
        authoritativePaneIds === null ||
        authoritativePaneIds.has(paneId)),
  );
}

function rootPaneIsVisible(panes: Record<string, ViewportPane>): boolean {
  return !Object.values(panes).some(
    (pane) => pane.kind !== "root" && pane.props.visible,
  );
}

function reconcilePaneLayout(
  layout: ViewportLayout,
  panes: Record<string, ViewportPane>,
  authoritativePaneIds: ReadonlySet<string> | null,
  omittedPaneId?: string,
): ViewportLayout {
  const paneIds = retainedPaneIds(layout, panes, authoritativePaneIds).filter(
    (paneId) => paneId !== omittedPaneId,
  );
  return reconcileViewportLayout(
    layout,
    paneIds,
    VIEWPORT_ROOT_PANE_ID,
    rootPaneIsVisible(panes),
  );
}

/** Per-viewer pane registry and browser-owned layout store. */
export function useViewportState(
  storage: ViewportLayoutStorage | null = browserStorage(),
): {
  store: Store<ViewportState>;
  actions: ViewportActions;
} {
  const store = React.useMemo(() => createStore(initialState()), []);
  const storageKeyRef = React.useRef<string | null>(null);
  const persistenceServerRef = React.useRef<string | null>(null);
  const authoritativePaneIdsRef = React.useRef<Set<string> | null>(null);

  const actions = React.useMemo<ViewportActions>(() => {
    const persistLayout = (layout: ViewportLayout): void => {
      const storageKey = storageKeyRef.current;
      if (storage === null || storageKey === null) return;
      try {
        storage.setItem(storageKey, JSON.stringify(layout));
      } catch {
        // Storage can be unavailable or full. Layout remains usable in memory.
      }
    };

    // Server-driven mutations (pane creates, visibility toggles, removals)
    // change the layout in memory only: persisting them would overwrite the
    // user's saved arrangement, e.g. a visibility round-trip would durably
    // lose the pane's position. Storage is written only for user gestures
    // and for authoritative snapshot reconciliation.
    const commitLayout = (
      layout: ViewportLayout,
      options?: { persist: boolean },
    ): boolean => {
      if (sameViewportLayout(layout, store.get().layout)) return false;
      if (options?.persist) persistLayout(layout);
      return true;
    };

    const addContentPane = (
      message: {
        pane_id: string;
        placement: ViewportPanePlacement;
        relative_to: string;
        equalize_group: readonly string[];
      },
      pane: ViewportContentPane,
    ): void => {
      const paneId = message.pane_id;
      if (paneId === VIEWPORT_ROOT_PANE_ID || paneId.length === 0) return;
      authoritativePaneIdsRef.current?.add(paneId);

      const state = store.get();
      const panes = copyPaneRecord(state.panes);
      panes[paneId] = pane;

      let layout = state.layout;
      if (!pane.props.visible) {
        layout = removeViewportPane(layout, paneId);
      } else if (!hasViewportPane(layout, paneId)) {
        const layoutPaneIds = collectViewportPaneIds(layout);
        const fallbackPaneId = layoutPaneIds[layoutPaneIds.length - 1];
        const relativeTo = hasViewportPane(layout, message.relative_to)
          ? message.relative_to
          : (fallbackPaneId ?? VIEWPORT_ROOT_PANE_ID);
        layout = insertViewportPane(
          layout,
          paneId,
          relativeTo,
          message.placement,
        );
        if (message.equalize_group.length > 0) {
          layout = equalizeViewportPanes(layout, [
            ...message.equalize_group,
            paneId,
          ]);
        }
      }

      layout = reconcilePaneLayout(
        layout,
        panes,
        authoritativePaneIdsRef.current,
      );

      if (commitLayout(layout)) store.set({ panes, layout });
      else store.set({ panes });
    };

    return {
      reset: () => {
        authoritativePaneIdsRef.current = null;
        store.set(
          initialState(initialLayout(), store.get().interactionEpoch + 1),
        );
      },

      resetPanes: () => {
        authoritativePaneIdsRef.current = null;
        store.set((state) => ({
          panes: initialPanes(),
          interactionEpoch: state.interactionEpoch + 1,
        }));
      },

      setPersistenceServer: (serverUrl) => {
        if (persistenceServerRef.current === serverUrl) return;
        persistenceServerRef.current = serverUrl;
        storageKeyRef.current = null;
        authoritativePaneIdsRef.current = null;
        store.set(
          initialState(initialLayout(), store.get().interactionEpoch + 1),
        );
      },

      setPersistenceWorkspace: (workspaceId) => {
        const serverUrl = persistenceServerRef.current;
        if (serverUrl === null) return;
        const storageKey = viewportLayoutStorageKey(serverUrl, workspaceId);
        if (storageKeyRef.current === storageKey) return;
        storageKeyRef.current = storageKey;
        authoritativePaneIdsRef.current = null;

        let layout = initialLayout();
        if (storage !== null) {
          try {
            const serialized = storage.getItem(storageKey);
            if (serialized !== null) {
              layout = normalizeViewportLayout(JSON.parse(serialized));
              storage.setItem(storageKey, JSON.stringify(layout));
            }
          } catch {
            // Malformed or inaccessible storage falls back to the root sentinel.
          }
        }
        store.set(initialState(layout, store.get().interactionEpoch + 1));
      },

      addImagePane: (message) => {
        addContentPane(message, {
          kind: "image",
          paneId: message.pane_id,
          props: message.props,
        });
      },

      addPlotlyPane: (message) => {
        addContentPane(message, {
          kind: "plotly",
          paneId: message.pane_id,
          props: message.props,
        });
      },

      addViserPane: (message) => {
        addContentPane(message, {
          kind: "viser",
          paneId: message.pane_id,
          props: message.props,
        });
      },

      updatePane: (paneId, updates) => {
        const state = store.get();
        const pane = state.panes[paneId];
        if (pane === undefined) return;

        const panes = copyPaneRecord(state.panes);
        if (pane.kind === "root") {
          if (
            typeof updates.visible !== "boolean" ||
            updates.visible === pane.visible
          ) {
            return;
          }
          panes[paneId] = { ...pane, visible: updates.visible };
          const layout = reconcilePaneLayout(
            state.layout,
            panes,
            authoritativePaneIdsRef.current,
          );
          if (commitLayout(layout)) store.set({ panes, layout });
          else store.set({ panes });
          return;
        }

        // The server only sends updates matching the pane's kind, which the
        // type system cannot prove across the content-pane union.
        const updatedPane = {
          ...pane,
          props: { ...pane.props, ...updates },
        } as ViewportContentPane;
        panes[paneId] = updatedPane;

        let layout = state.layout;
        if (updatedPane.props.visible !== pane.props.visible) {
          if (updatedPane.props.visible) {
            const layoutPaneIds = collectViewportPaneIds(layout);
            const fallbackPaneId = layoutPaneIds[layoutPaneIds.length - 1];
            layout = insertViewportPane(
              layout,
              paneId,
              hasViewportPane(layout, VIEWPORT_ROOT_PANE_ID)
                ? VIEWPORT_ROOT_PANE_ID
                : (fallbackPaneId ?? VIEWPORT_ROOT_PANE_ID),
              "right",
            );
          } else {
            layout = removeViewportPane(layout, paneId);
          }
          layout = reconcilePaneLayout(
            layout,
            panes,
            authoritativePaneIdsRef.current,
          );
        }

        if (commitLayout(layout)) store.set({ panes, layout });
        else store.set({ panes });
      },

      removePane: (paneId) => {
        if (paneId === VIEWPORT_ROOT_PANE_ID) return;
        authoritativePaneIdsRef.current?.delete(paneId);
        const state = store.get();
        const panes = copyPaneRecord(state.panes);
        delete panes[paneId];
        let layout = removeViewportPane(state.layout, paneId);
        layout = reconcilePaneLayout(
          layout,
          panes,
          authoritativePaneIdsRef.current,
          paneId,
        );
        if (commitLayout(layout)) store.set({ panes, layout });
        else store.set({ panes });
      },

      setPaneSnapshot: (paneIds) => {
        const authoritativePaneIds = new Set(
          paneIds.filter(
            (paneId) => paneId.length > 0 && paneId !== VIEWPORT_ROOT_PANE_ID,
          ),
        );
        authoritativePaneIdsRef.current = authoritativePaneIds;

        const state = store.get();
        const panes = copyPaneRecord(state.panes);
        Object.keys(panes).forEach((paneId) => {
          if (
            paneId !== VIEWPORT_ROOT_PANE_ID &&
            !authoritativePaneIds.has(paneId)
          ) {
            delete panes[paneId];
          }
        });

        // Retain saved leaves named by the snapshot even if their create has
        // not arrived yet, but do not invent leaves for unhydrated IDs.
        const layout = reconcilePaneLayout(
          state.layout,
          panes,
          authoritativePaneIds,
        );
        // The snapshot is the authoritative reconciliation point: persist
        // even when the in-memory layout already reflects it, since earlier
        // server-driven mutations (creates, removals) deliberately don't.
        persistLayout(layout);
        if (commitLayout(layout)) store.set({ panes, layout });
        else store.set({ panes });
      },

      commitUserLayout: (rawLayout) => {
        const state = store.get();
        const normalized = normalizeViewportLayout(rawLayout);
        const layout = reconcilePaneLayout(
          normalized,
          state.panes,
          authoritativePaneIdsRef.current,
        );
        if (commitLayout(layout, { persist: true })) store.set({ layout });
      },
    };
  }, [storage, store]);

  return { store, actions };
}
