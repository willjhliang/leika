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
import {
  isBoundedLayoutId,
  parseBoundedPersistedJson,
} from "../persistenceLimits";
import type { Message } from "../WebsocketMessages";
import {
  MAX_LIVE_VIEWPORT_CONTENT_PANES,
  viewportPanesWithinAggregateLimits,
} from "./viewportLimits";

export type ViewportPanePlacement = Exclude<ViewportDropRegion, "center">;

export interface ViewportImageProps {
  _data: Uint8Array<ArrayBuffer> | null;
  _format: "jpeg" | "png";
  title: string;
  visible: boolean;
  /** `null` defers to the viewer's own "Image fit" setting. */
  fit: ImageFit | null;
}

export interface ViewportMatplotlibProps {
  /** Figure SVG source, rendered as-is and scaled to the pane. */
  _svg: string;
  title: string;
  visible: boolean;
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

export interface ViewportMatplotlibPane {
  kind: "matplotlib";
  paneId: string;
  props: ViewportMatplotlibProps;
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
  | ViewportMatplotlibPane
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

export interface ViewportMatplotlibDeclaration {
  pane_id: string;
  props: ViewportMatplotlibProps;
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
  | Partial<ViewportMatplotlibProps>
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
  addMatplotlibPane: (message: ViewportMatplotlibDeclaration) => void;
  addPlotlyPane: (message: ViewportPlotlyDeclaration) => void;
  addViserPane: (message: ViewportViserDeclaration) => void;
  updatePane: (paneId: string, updates: ViewportPaneUpdates) => void;
  removePane: (paneId: string) => void;
  setPaneSnapshot: (paneIds: readonly string[]) => void;
  commitUserLayout: (layout: ViewportLayout) => void;
  /** Pure admission for viewport state owned by one original wire frame. */
  preflightMessageBatch: (messages: readonly Message[]) => string | null;
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

function contentPaneFromMessage(message: Message): ViewportContentPane | null {
  switch (message.type) {
    case "ViewportImageMessage":
      return { kind: "image", paneId: message.pane_id, props: message.props };
    case "ViewportMatplotlibMessage":
      return {
        kind: "matplotlib",
        paneId: message.pane_id,
        props: message.props,
      };
    case "ViewportPlotlyMessage":
      return { kind: "plotly", paneId: message.pane_id, props: message.props };
    case "ViewportViserMessage":
      return { kind: "viser", paneId: message.pane_id, props: message.props };
    default:
      return null;
  }
}

function panePropsHaveValidShape(pane: ViewportContentPane): boolean {
  if (
    typeof pane.props.title !== "string" ||
    typeof pane.props.visible !== "boolean"
  )
    return false;
  if (pane.kind === "image") {
    const props = pane.props;
    return (
      Object.keys(props).length === 5 &&
      (props._data === null || props._data instanceof Uint8Array) &&
      (props._format === "jpeg" || props._format === "png") &&
      (props.fit === null ||
        props.fit === "fit" ||
        props.fit === "fill" ||
        props.fit === "stretch")
    );
  }
  if (pane.kind === "matplotlib") {
    const props = pane.props;
    return Object.keys(props).length === 3 && typeof props._svg === "string";
  }
  if (pane.kind === "plotly") {
    const props = pane.props;
    return (
      Object.keys(props).length === 4 &&
      typeof props._plotly_json_str === "string" &&
      typeof props._theme_templates === "string"
    );
  }
  const props = pane.props;
  return (
    Object.keys(props).length === 4 &&
    (props._url === null || typeof props._url === "string") &&
    (props._port === null || Number.isSafeInteger(props._port)) &&
    (props._url === null) !== (props._port === null)
  );
}

function detachViewportPaneBinary(
  pane: ViewportContentPane,
): ViewportContentPane {
  if (pane.kind !== "image" || pane.props._data === null) return pane;
  return {
    ...pane,
    props: { ...pane.props, _data: pane.props._data.slice() },
  };
}

function equalizeGroupIsValid(
  paneId: string,
  group: readonly string[],
): boolean {
  if (group.length > MAX_LIVE_VIEWPORT_CONTENT_PANES) return false;
  const unique = new Set<string>();
  for (const id of group) {
    if (
      !isBoundedLayoutId(id) ||
      id === VIEWPORT_ROOT_PANE_ID ||
      id === paneId ||
      unique.has(id)
    ) {
      return false;
    }
    unique.add(id);
  }
  return true;
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
  const contentPaneCountRef = React.useRef(0);

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
      const state = store.get();
      const alreadyDeclared = Object.hasOwn(state.panes, paneId);
      const authoritativePaneIds = authoritativePaneIdsRef.current;
      if (
        (!alreadyDeclared &&
          contentPaneCountRef.current >= MAX_LIVE_VIEWPORT_CONTENT_PANES) ||
        (authoritativePaneIds !== null &&
          !authoritativePaneIds.has(paneId) &&
          authoritativePaneIds.size >= MAX_LIVE_VIEWPORT_CONTENT_PANES)
      ) {
        return;
      }
      authoritativePaneIds?.add(paneId);
      const panes = copyPaneRecord(state.panes);
      panes[paneId] = detachViewportPaneBinary(pane);
      if (!alreadyDeclared) contentPaneCountRef.current += 1;

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

    const preflightMessageBatch = (
      messages: readonly Message[],
    ): string | null => {
      const panes = new Map<string, ViewportContentPane>();
      for (const pane of Object.values(store.get().panes)) {
        if (pane.kind !== "root") panes.set(pane.paneId, pane);
      }
      let authoritativePaneIds =
        authoritativePaneIdsRef.current === null
          ? null
          : new Set(authoritativePaneIdsRef.current);
      const reject = (detail: string) =>
        "Connection frame violates viewport safety limits: " + detail;

      for (const message of messages) {
        const declaration = contentPaneFromMessage(message);
        if (declaration !== null) {
          if (
            message.type === "ViewportImageMessage" ||
            message.type === "ViewportMatplotlibMessage" ||
            message.type === "ViewportPlotlyMessage" ||
            message.type === "ViewportViserMessage"
          ) {
            if (
              !isBoundedLayoutId(message.relative_to) ||
              !equalizeGroupIsValid(message.pane_id, message.equalize_group)
            )
              return reject("pane placement identifiers are invalid");
          }
          if (
            !isBoundedLayoutId(declaration.paneId) ||
            declaration.paneId === VIEWPORT_ROOT_PANE_ID ||
            !panePropsHaveValidShape(declaration)
          ) {
            return reject("pane declaration is invalid");
          }
          if (
            !panes.has(declaration.paneId) &&
            panes.size >= MAX_LIVE_VIEWPORT_CONTENT_PANES
          ) {
            return reject("live pane owner limit exceeded");
          }
          if (
            authoritativePaneIds !== null &&
            !authoritativePaneIds.has(declaration.paneId) &&
            authoritativePaneIds.size >= MAX_LIVE_VIEWPORT_CONTENT_PANES
          ) {
            return reject("authoritative pane owner limit exceeded");
          }
          panes.set(declaration.paneId, declaration);
          authoritativePaneIds?.add(declaration.paneId);
          if (!viewportPanesWithinAggregateLimits(panes.values())) {
            return reject("pane source, renderer, or iframe budget exceeded");
          }
          continue;
        }
        if (message.type === "ViewportPaneUpdateMessage") {
          if (!isBoundedLayoutId(message.pane_id)) {
            return reject("pane update identifier is invalid");
          }
          const previous = panes.get(message.pane_id);
          if (previous === undefined) continue;
          const candidate = {
            ...previous,
            props: { ...previous.props, ...message.updates },
          } as ViewportContentPane;
          if (
            !panePropsHaveValidShape(candidate) ||
            !viewportPanesWithinAggregateLimits(
              [...panes.values()].map((pane) =>
                pane.paneId === message.pane_id ? candidate : pane,
              ),
            )
          ) {
            return reject("pane update violates its schema or budget");
          }
          panes.set(message.pane_id, candidate);
        } else if (message.type === "ViewportPaneRemoveMessage") {
          if (!isBoundedLayoutId(message.pane_id)) {
            return reject("pane removal identifier is invalid");
          }
          panes.delete(message.pane_id);
          authoritativePaneIds?.delete(message.pane_id);
        } else if (message.type === "ViewportPaneSnapshotMessage") {
          if (message.pane_ids.length > MAX_LIVE_VIEWPORT_CONTENT_PANES) {
            return reject("pane snapshot owner limit exceeded");
          }
          authoritativePaneIds = new Set<string>();
          for (const paneId of message.pane_ids) {
            if (
              !isBoundedLayoutId(paneId) ||
              paneId === VIEWPORT_ROOT_PANE_ID ||
              authoritativePaneIds.has(paneId)
            ) {
              return reject("pane snapshot identifiers are invalid");
            }
            authoritativePaneIds.add(paneId);
          }
          for (const paneId of panes.keys()) {
            if (!authoritativePaneIds.has(paneId)) panes.delete(paneId);
          }
        } else if (
          message.type === "WorkspaceConfigurationMessage" &&
          !isBoundedLayoutId(message.workspace_id)
        ) {
          return reject("workspace identifier is invalid");
        }
      }
      return null;
    };

    const directMessage = (type: Message["type"], value: object): Message =>
      ({ type, ...value }) as Message;

    const admitDirect = (message: Message): boolean => {
      const failure = preflightMessageBatch([message]);
      if (failure === null) return true;
      console.error(failure);
      return false;
    };

    return {
      reset: () => {
        authoritativePaneIdsRef.current = null;
        contentPaneCountRef.current = 0;
        store.set(
          initialState(initialLayout(), store.get().interactionEpoch + 1),
        );
      },

      resetPanes: () => {
        authoritativePaneIdsRef.current = null;
        contentPaneCountRef.current = 0;
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
        contentPaneCountRef.current = 0;
        store.set(
          initialState(initialLayout(), store.get().interactionEpoch + 1),
        );
      },

      setPersistenceWorkspace: (workspaceId) => {
        const serverUrl = persistenceServerRef.current;
        if (serverUrl === null || !isBoundedLayoutId(workspaceId)) return;
        const storageKey = viewportLayoutStorageKey(serverUrl, workspaceId);
        if (storageKeyRef.current === storageKey) return;
        storageKeyRef.current = storageKey;
        authoritativePaneIdsRef.current = null;
        contentPaneCountRef.current = 0;

        let layout = initialLayout();
        if (storage !== null) {
          let storedLayout: ViewportLayout | null = null;
          try {
            const serialized = storage.getItem(storageKey);
            if (serialized !== null) {
              storedLayout = normalizeViewportLayout(
                parseBoundedPersistedJson(serialized),
              );
            }
          } catch {
            // Malformed or inaccessible storage falls back to the root sentinel.
          }
          if (storedLayout !== null) {
            layout = storedLayout;
            try {
              storage.setItem(storageKey, JSON.stringify(layout));
            } catch {
              // A read-only/full store must not discard a layout already read.
            }
          }
        }
        store.set(initialState(layout, store.get().interactionEpoch + 1));
      },

      addImagePane: (message) => {
        if (!admitDirect(directMessage("ViewportImageMessage", message)))
          return;
        addContentPane(message, {
          kind: "image",
          paneId: message.pane_id,
          props: message.props,
        });
      },

      addMatplotlibPane: (message) => {
        if (!admitDirect(directMessage("ViewportMatplotlibMessage", message)))
          return;
        addContentPane(message, {
          kind: "matplotlib",
          paneId: message.pane_id,
          props: message.props,
        });
      },

      addPlotlyPane: (message) => {
        if (!admitDirect(directMessage("ViewportPlotlyMessage", message)))
          return;
        addContentPane(message, {
          kind: "plotly",
          paneId: message.pane_id,
          props: message.props,
        });
      },

      addViserPane: (message) => {
        if (!admitDirect(directMessage("ViewportViserMessage", message)))
          return;
        addContentPane(message, {
          kind: "viser",
          paneId: message.pane_id,
          props: message.props,
        });
      },

      updatePane: (paneId, updates) => {
        if (
          !admitDirect(
            directMessage("ViewportPaneUpdateMessage", {
              pane_id: paneId,
              updates,
            }),
          )
        )
          return;
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
        panes[paneId] = detachViewportPaneBinary(updatedPane);

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
        if (Object.hasOwn(panes, paneId)) {
          contentPaneCountRef.current -= 1;
        }
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
        // Reject before constructing a Set: the wire schema permits much
        // larger arrays than the viewport can ever reconcile or render.
        if (
          !admitDirect(
            directMessage("ViewportPaneSnapshotMessage", {
              pane_ids: paneIds,
            }),
          )
        )
          return;
        const authoritativePaneIds = new Set<string>();
        for (const paneId of paneIds) {
          if (paneId.length > 0 && paneId !== VIEWPORT_ROOT_PANE_ID) {
            authoritativePaneIds.add(paneId);
          }
        }
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
        contentPaneCountRef.current = Object.keys(panes).length - 1;

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
      preflightMessageBatch,
    };
  }, [storage, store]);

  return { store, actions };
}
