import React from "react";

import { ImageFit } from "../ClientSettings";
import { createStore, Store } from "../store";
import {
  ViewportLayout,
  collectViewportPaneIds,
  equalizeViewportPanes,
  hasViewportPane,
  normalizeViewportLayout,
  placeViewportPane,
  reconcileViewportLayout,
  removeViewportPane,
  sameViewportLayout,
} from "./layoutModel";
import { parseBoundedPersistedJson } from "../persistenceLimits";
import type { Message } from "../WebsocketMessages";

interface RefreshableProps {
  _refresh_controls?: readonly string[];
  _refresh_revision?: number;
  _refresh_requests?: readonly string[];
}

interface RefreshablePane {
  refreshPending?: { requestId: string | null; minimumRevision: number };
}

export interface ViewportEmptyProps extends RefreshableProps {
  title: string;
  visible: boolean;
  loading: boolean | string;
}

export interface ViewportEmptyPane extends RefreshablePane {
  kind: "empty";
  paneId: string;
  props: ViewportEmptyProps;
}

export interface ViewportImageProps extends RefreshableProps {
  _data: Uint8Array<ArrayBuffer> | null;
  _format: "jpeg" | "png";
  title: string;
  visible: boolean;
  loading: boolean | string;
  /** `null` defers to the viewer's own "Image fit" setting. */
  fit: ImageFit | null;
}

export interface ViewportMatplotlibProps extends RefreshableProps {
  /** Figure SVG source, rendered as-is and scaled to the pane. */
  _svg: string;
  title: string;
  visible: boolean;
  loading: boolean | string;
}

export interface ViewportPlotlyProps extends RefreshableProps {
  _plotly_json_str: string;
  /** JSON string with "light"/"dark" template definitions, applied when the
   * figure does not specify a template. */
  _theme_templates: string;
  title: string;
  visible: boolean;
  loading: boolean | string;
}

export interface ViewportVideoProps extends RefreshableProps {
  _url: string;
  autoplay: boolean;
  loop: boolean;
  muted: boolean;
  controls: boolean;
  sync_group: string | null;
  fps: number | null;
  title: string;
  visible: boolean;
  loading: boolean | string;
}

export interface ViewportViserProps extends RefreshableProps {
  /** Same-origin proxy path or absolute embed URL, rendered near-verbatim. */
  _url: string;
  title: string;
  visible: boolean;
  loading: boolean | string;
}

export interface ViewportImagePane extends RefreshablePane {
  kind: "image";
  paneId: string;
  props: ViewportImageProps;
}

export interface ViewportMatplotlibPane extends RefreshablePane {
  kind: "matplotlib";
  paneId: string;
  props: ViewportMatplotlibProps;
}

export interface ViewportPlotlyPane extends RefreshablePane {
  kind: "plotly";
  paneId: string;
  props: ViewportPlotlyProps;
}

export interface ViewportVideoPane extends RefreshablePane {
  kind: "video";
  paneId: string;
  props: ViewportVideoProps;
}

export interface ViewportViserPane extends RefreshablePane {
  kind: "viser";
  paneId: string;
  props: ViewportViserProps;
}

/** A server-declared pane and its content. */
export type ViewportPane =
  | ViewportEmptyPane
  | ViewportImagePane
  | ViewportMatplotlibPane
  | ViewportPlotlyPane
  | ViewportViserPane
  | ViewportVideoPane;

export interface ViewportPageState {
  pageId: string;
  name: string;
  isDefault: boolean;
  panes: Record<string, ViewportPane>;
  layout: ViewportLayout;
}
export interface ViewportPageStream {
  pageId: string;
  generation: number;
  accepting: boolean;
  ready: boolean;
}

export interface ViewportState {
  pages: Record<string, ViewportPageState>;
  pageOrder: string[];
  activePageId: string | null;
  displayPageId: string | null;
  warmPage: ViewportPageState | null;
  transitionPage: ViewportPageState | null;
  catalogReady: boolean;
  pageStream: ViewportPageStream | null;
  interactionEpoch: number;
}

/** Whether the active page's complete live generation may accept interaction. */
export function isViewportPageReady(state: ViewportState): boolean {
  const pageId = state.displayPageId;
  const stream = state.pageStream;
  return (
    pageId !== null &&
    state.transitionPage === null &&
    state.activePageId === pageId &&
    stream !== null &&
    stream.pageId === pageId &&
    stream.ready
  );
}

/** The wire messages that declare a pane or replace its content. */
export type ViewportPaneCreateMessage = Extract<
  Message,
  {
    type:
      | "ViewportPaneMessage"
      | "ViewportEmptyMessage"
      | "ViewportImageMessage"
      | "ViewportMatplotlibMessage"
      | "ViewportPlotlyMessage"
      | "ViewportVideoMessage"
      | "ViewportViserMessage";
  }
>;

// A union of Partials rather than a Partial of an intersection, so that
// same-named props with different types never collapse across pane kinds.
export type ViewportPaneUpdates =
  | Partial<ViewportEmptyProps>
  | Partial<ViewportImageProps>
  | Partial<ViewportMatplotlibProps>
  | Partial<ViewportPlotlyProps>
  | Partial<ViewportViserProps>
  | Partial<ViewportVideoProps>;

export interface ViewportActions {
  /** Clear pane contents for a new connection while retaining browser layout. */
  resetPanes: () => void;
  /** Retain the displayed page while a connection replays its catalog. */
  reconnect: () => void;
  /** Select the websocket server portion of the persistence namespace. */
  setPersistenceServer: (serverUrl: string) => void;
  /** Restore the workspace-specific persisted layout. */
  setPersistenceWorkspace: (workspaceId: string) => void;
  addPage: (pageId: string, name: string, isDefault: boolean) => void;
  updatePage: (pageId: string, name: string) => void;
  setActivePage: (pageId: string) => void;
  finishPageCatalog: (pageIds: readonly string[]) => void;
  beginPageSubscription: (pageId: string, generation: number) => void;
  beginPageStream: (pageId: string, generation: number) => void;
  finishPageStream: (pageId: string, generation: number) => void;
  addPane: (message: ViewportPaneCreateMessage) => void;
  updatePane: (
    pageId: string,
    paneId: string,
    updates: ViewportPaneUpdates,
  ) => void;
  invalidateForInput: (uuid: string, requestId: string) => boolean;
  removePane: (pageId: string, paneId: string) => void;
  setPaneSnapshot: (pageId: string, paneIds: readonly string[]) => void;
  commitUserLayout: (layout: ViewportLayout) => void;
}

export interface ViewportLayoutStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const STORAGE_KEY_PREFIX = "leika.viewport.layout.v3:";
const ACTIVE_PAGE_STORAGE_KEY_PREFIX = "leika.viewport.active-page.v1:";

export function viewportLayoutStorageKey(
  serverUrl: string,
  workspaceId: string,
  pageId = "default",
): string {
  return STORAGE_KEY_PREFIX + JSON.stringify([serverUrl, workspaceId, pageId]);
}

export function activeViewportPageStorageKey(
  serverUrl: string,
  workspaceId: string,
): string {
  return (
    ACTIVE_PAGE_STORAGE_KEY_PREFIX + JSON.stringify([serverUrl, workspaceId])
  );
}

function browserStorage(): ViewportLayoutStorage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function initialViewportLayout(): ViewportLayout {
  return { version: 1, root: null };
}

export function initialViewportPanes(): Record<string, ViewportPane> {
  return Object.create(null) as Record<string, ViewportPane>;
}

function initialState(interactionEpoch = 0): ViewportState {
  return {
    pages: Object.create(null) as Record<string, ViewportPageState>,
    pageOrder: [],
    activePageId: null,
    displayPageId: null,
    warmPage: null,
    transitionPage: null,
    catalogReady: false,
    pageStream: null,
    interactionEpoch,
  };
}

function copyPaneRecord(
  panes: Record<string, ViewportPane>,
): Record<string, ViewportPane> {
  return Object.assign(
    Object.create(null) as Record<string, ViewportPane>,
    panes,
  );
}

function paneFromMessage(message: ViewportPaneCreateMessage): ViewportPane {
  switch (message.type) {
    case "ViewportPaneMessage":
    case "ViewportEmptyMessage":
      return { kind: "empty", paneId: message.pane_id, props: message.props };
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
    case "ViewportVideoMessage":
      return { kind: "video", paneId: message.pane_id, props: message.props };
    case "ViewportViserMessage":
      return { kind: "viser", paneId: message.pane_id, props: message.props };
  }
}

function detachViewportPaneBinary(
  pane: ViewportPane,
  previous?: ViewportPane,
): ViewportPane {
  if (pane.kind !== "image" || pane.props._data === null) return pane;
  // Reuse bytes already detached from their wire frame when only title,
  // visibility, loading or fit changes. New incoming buffers still get copied.
  if (previous?.kind === "image" && pane.props._data === previous.props._data)
    return pane;
  return {
    ...pane,
    props: { ...pane.props, _data: pane.props._data.slice() },
  };
}

function retainedPaneIds(
  layout: ViewportLayout,
  panes: Record<string, ViewportPane>,
  authoritativePaneIds: ReadonlySet<string> | null,
): string[] {
  return collectViewportPaneIds(layout).filter(
    (paneId) =>
      (panes[paneId]?.props.visible ?? true) &&
      (authoritativePaneIds === null || authoritativePaneIds.has(paneId)),
  );
}

function reconcilePaneLayout(
  layout: ViewportLayout,
  panes: Record<string, ViewportPane>,
  authoritativePaneIds: ReadonlySet<string> | null,
): ViewportLayout {
  return reconcileViewportLayout(
    layout,
    retainedPaneIds(layout, panes, authoritativePaneIds),
  );
}

/** Per-viewer page catalog, pane registries, and browser-owned layout store. */
export function createViewportState(
  storage: ViewportLayoutStorage | null = browserStorage(),
): {
  store: Store<ViewportState>;
  actions: ViewportActions;
} {
  const store = createStore(initialState());
  let persistenceServer: string | null = null;
  let persistenceWorkspace: string | null = null;
  let preferredActivePageId: string | null = null;
  const authoritativePanesByPage = new Map<string, Set<string> | null>();

  const layoutKey = (pageId: string): string | null => {
    const server = persistenceServer;
    const workspace = persistenceWorkspace;
    return server === null || workspace === null
      ? null
      : viewportLayoutStorageKey(server, workspace, pageId);
  };

  const persistLayout = (pageId: string, layout: ViewportLayout): void => {
    const key = layoutKey(pageId);
    if (storage === null || key === null) return;
    try {
      storage.setItem(key, JSON.stringify(layout));
    } catch {
      // Storage can be unavailable or full. Layout remains usable in memory.
    }
  };

  const readLayout = (pageId: string): ViewportLayout => {
    const key = layoutKey(pageId);
    if (storage === null || key === null) return initialViewportLayout();
    try {
      const serialized = storage.getItem(key);
      return serialized === null
        ? initialViewportLayout()
        : normalizeViewportLayout(parseBoundedPersistedJson(serialized));
    } catch {
      return initialViewportLayout();
    }
  };

  const persistActivePage = (pageId: string): void => {
    const server = persistenceServer;
    const workspace = persistenceWorkspace;
    if (storage === null || server === null || workspace === null) return;
    try {
      storage.setItem(activeViewportPageStorageKey(server, workspace), pageId);
    } catch {
      // Selection persistence is best-effort, like layout persistence.
    }
  };

  const clearCatalogPageModels = (
    pages: Record<string, ViewportPageState>,
  ): Record<string, ViewportPageState> => {
    const cleared = Object.create(null) as Record<string, ViewportPageState>;
    for (const [pageId, page] of Object.entries(pages)) {
      authoritativePanesByPage.set(pageId, null);
      cleared[pageId] = { ...page, panes: initialViewportPanes() };
    }
    return cleared;
  };

  const replacePage = (page: ViewportPageState): void => {
    const state = store.get();
    store.set({ pages: { ...state.pages, [page.pageId]: page } });
  };

  // Server-driven mutations change layouts in memory only. Persisting them
  // would overwrite a user's arrangement during a visibility round-trip.
  const commitPageLayout = (
    page: ViewportPageState,
    layout: ViewportLayout,
    persist = false,
  ): boolean => {
    if (sameViewportLayout(layout, page.layout)) return false;
    if (persist) persistLayout(page.pageId, layout);
    return true;
  };

  /** Pane messages apply only to the page stream this browser subscribed to,
   * so frames from a superseded page or generation are ignored. */
  const streamedPage = (pageId: string): ViewportPageState | undefined => {
    const { pageStream, pages } = store.get();
    return pageStream?.accepting && pageStream.pageId === pageId
      ? pages[pageId]
      : undefined;
  };

  const addPane = (message: ViewportPaneCreateMessage): void => {
    const page = streamedPage(message.page_id);
    if (page === undefined) return;
    const paneId = message.pane_id;
    const pane = paneFromMessage(message);
    const authoritativePaneIds =
      authoritativePanesByPage.get(page.pageId) ?? null;
    authoritativePaneIds?.add(paneId);
    const panes = copyPaneRecord(page.panes);
    panes[paneId] = detachViewportPaneBinary(pane, page.panes[paneId]);

    let layout = page.layout;
    if (!pane.props.visible) {
      layout = removeViewportPane(layout, paneId);
    } else if (!hasViewportPane(layout, paneId)) {
      const savedLayout = readLayout(page.pageId);
      if (hasViewportPane(savedLayout, paneId)) {
        // A page declaration and its initial empty snapshot can reach an
        // already-connected browser before Python declares that page's
        // panes. Recover each arriving pane from the browser-owned layout
        // instead of replacing that layout with creation-time hints.
        layout = savedLayout;
      } else {
        layout = placeViewportPane(
          layout,
          paneId,
          message.relative_to,
          message.placement,
        );
        if (message.equalize_group.length > 0) {
          layout = equalizeViewportPanes(layout, [
            ...message.equalize_group,
            paneId,
          ]);
        }
      }
    }
    layout = reconcilePaneLayout(layout, panes, authoritativePaneIds);
    replacePage({ ...page, panes, layout });
  };

  const clearPages = (): void => {
    authoritativePanesByPage.clear();
    store.set(initialState(store.get().interactionEpoch + 1));
  };

  const actions: ViewportActions = {
    resetPanes: clearPages,

    reconnect: () => {
      const state = store.get();
      // Reuse the page-transition owner: one snapshot stays mounted until a
      // complete stream replaces it. New workspace/server identities clear it.
      const transitionPage =
        state.transitionPage ??
        (state.displayPageId !== null && state.pageStream?.ready
          ? (state.pages[state.displayPageId] ?? null)
          : null);
      preferredActivePageId = state.activePageId ?? preferredActivePageId;
      authoritativePanesByPage.clear();
      const next = {
        ...initialState(state.interactionEpoch + 1),
        activePageId: state.activePageId,
        displayPageId: transitionPage?.pageId ?? null,
        transitionPage,
      };
      store.set(next);
    },

    setPersistenceServer: (serverUrl) => {
      if (persistenceServer === serverUrl) return;
      persistenceServer = serverUrl;
      persistenceWorkspace = null;
      preferredActivePageId = null;
      clearPages();
    },

    setPersistenceWorkspace: (workspaceId) => {
      const serverUrl = persistenceServer;
      if (serverUrl === null || persistenceWorkspace === workspaceId) return;
      persistenceWorkspace = workspaceId;
      preferredActivePageId = null;
      if (storage !== null) {
        try {
          preferredActivePageId = storage.getItem(
            activeViewportPageStorageKey(serverUrl, workspaceId),
          );
        } catch {
          // Inaccessible storage simply starts on the default page.
        }
      }
      clearPages();
    },

    addPage: (pageId, name, isDefault) => {
      const state = store.get();
      const page: ViewportPageState = {
        pageId,
        name,
        isDefault,
        panes: initialViewportPanes(),
        layout: readLayout(pageId),
      };
      authoritativePanesByPage.set(pageId, null);
      store.set({
        pages: { ...state.pages, [pageId]: page },
        pageOrder: [...state.pageOrder, pageId],
        catalogReady: false,
      });
    },

    updatePage: (pageId, name) => {
      const state = store.get();
      const page = state.pages[pageId];
      const pages =
        page !== undefined && page.name !== name
          ? { ...state.pages, [pageId]: { ...page, name } }
          : state.pages;
      const warmPage =
        state.warmPage?.pageId === pageId
          ? { ...state.warmPage, name }
          : state.warmPage;
      const transitionPage =
        state.transitionPage?.pageId === pageId
          ? { ...state.transitionPage, name }
          : state.transitionPage;
      if (
        pages !== state.pages ||
        warmPage !== state.warmPage ||
        transitionPage !== state.transitionPage
      )
        store.set({ pages, warmPage, transitionPage });
    },

    finishPageCatalog: (pageIds) => {
      const state = store.get();
      const preferred = preferredActivePageId;
      const defaultPageId = state.pageOrder.find(
        (pageId) => state.pages[pageId]?.isDefault,
      );
      const activePageId =
        preferred !== null && pageIds.includes(preferred)
          ? preferred
          : state.activePageId !== null && pageIds.includes(state.activePageId)
            ? state.activePageId
            : (defaultPageId ?? pageIds[0] ?? null);
      const activeChanged = activePageId !== state.activePageId;
      const pages = activeChanged
        ? clearCatalogPageModels(state.pages)
        : state.pages;
      const warmPage = activeChanged ? null : state.warmPage;
      const transitionPage = activeChanged ? null : state.transitionPage;
      store.set({
        pages,
        activePageId,
        displayPageId: activeChanged ? null : state.displayPageId,
        warmPage,
        transitionPage,
        catalogReady: true,
        pageStream: activeChanged ? null : state.pageStream,
        interactionEpoch: activeChanged
          ? state.interactionEpoch + 1
          : state.interactionEpoch,
      });
    },

    beginPageSubscription: (pageId, generation) => {
      const state = store.get();
      if (
        state.activePageId !== pageId ||
        state.pages[pageId] === undefined ||
        (state.pageStream?.pageId === pageId &&
          state.pageStream.generation === generation)
      )
        return;

      let transitionPage = state.transitionPage;
      let warmPage = state.warmPage;
      if (
        transitionPage === null &&
        state.displayPageId === pageId &&
        state.pageStream?.pageId === pageId &&
        state.pageStream.ready
      ) {
        transitionPage = state.pages[pageId];
        if (warmPage?.pageId === pageId) warmPage = null;
      }
      const pages = clearCatalogPageModels(state.pages);
      const displayPageId = transitionPage?.pageId ?? null;
      store.set({
        pages,
        displayPageId,
        warmPage,
        transitionPage,
        pageStream: {
          pageId,
          generation,
          accepting: false,
          ready: false,
        },
        interactionEpoch: state.interactionEpoch + 1,
      });
    },

    beginPageStream: (pageId, generation) => {
      const state = store.get();
      const stream = state.pageStream;
      if (
        state.activePageId !== pageId ||
        stream === null ||
        stream.pageId !== pageId ||
        stream.generation !== generation ||
        stream.accepting
      )
        return;
      store.set({ pageStream: { ...stream, accepting: true } });
    },

    finishPageStream: (pageId, generation) => {
      const state = store.get();
      const stream = state.pageStream;
      if (
        state.activePageId !== pageId ||
        stream === null ||
        stream.pageId !== pageId ||
        stream.generation !== generation ||
        !stream.accepting
      )
        return;
      let warmPage = state.warmPage;
      if (
        state.transitionPage !== null &&
        state.transitionPage.pageId !== pageId
      )
        warmPage = state.transitionPage;
      if (warmPage?.pageId === pageId) warmPage = null;
      store.set({
        displayPageId: pageId,
        warmPage,
        transitionPage: null,
        pageStream: { ...stream, ready: true },
        interactionEpoch: state.interactionEpoch + 1,
      });
    },

    setActivePage: (pageId) => {
      const state = store.get();
      if (state.pages[pageId] === undefined || state.activePageId === pageId)
        return;

      const readyLivePage =
        state.transitionPage === null &&
        state.displayPageId === state.activePageId &&
        state.activePageId !== null &&
        state.pageStream?.pageId === state.activePageId &&
        state.pageStream.ready
          ? state.pages[state.activePageId]
          : null;
      const displayedPage =
        state.transitionPage?.pageId === state.displayPageId
          ? state.transitionPage
          : readyLivePage?.pageId === state.displayPageId
            ? readyLivePage
            : null;
      const targetSnapshot =
        state.transitionPage?.pageId === pageId
          ? state.transitionPage
          : state.warmPage?.pageId === pageId
            ? state.warmPage
            : null;

      let transitionPage: ViewportPageState | null;
      let warmPage: ViewportPageState | null;
      if (targetSnapshot !== null) {
        transitionPage = targetSnapshot;
        const candidates = [
          displayedPage,
          readyLivePage,
          state.transitionPage,
          state.warmPage,
        ];
        warmPage =
          candidates.find(
            (candidate) =>
              candidate !== null &&
              candidate !== targetSnapshot &&
              candidate.pageId !== pageId,
          ) ?? null;
      } else {
        transitionPage = displayedPage;
        warmPage = null;
      }

      const pages = clearCatalogPageModels(state.pages);
      const displayPageId = transitionPage?.pageId ?? null;
      preferredActivePageId = pageId;
      persistActivePage(pageId);
      store.set({
        pages,
        activePageId: pageId,
        displayPageId,
        warmPage,
        transitionPage,
        pageStream: null,
        interactionEpoch: state.interactionEpoch + 1,
      });
    },

    addPane,

    invalidateForInput: (uuid, requestId) => {
      const state = store.get();
      const page =
        state.displayPageId === null
          ? undefined
          : state.pages[state.displayPageId];
      if (page === undefined) return false;
      const panes = copyPaneRecord(page.panes);
      let changed = false;
      for (const [paneId, pane] of Object.entries(panes)) {
        if (!pane.props._refresh_controls?.includes(uuid)) continue;
        panes[paneId] = {
          ...pane,
          refreshPending: {
            requestId,
            minimumRevision: pane.props._refresh_revision ?? 0,
          },
        };
        changed = true;
      }
      if (changed) replacePage({ ...page, panes });
      return changed;
    },

    updatePane: (pageId, paneId, updates) => {
      const page = streamedPage(pageId);
      const pane = page?.panes[paneId];
      if (page === undefined || pane === undefined) return;
      const revision = updates._refresh_revision ?? 0;
      const pending = pane.refreshPending;
      if (
        (pending !== undefined &&
          !updates._refresh_requests?.includes(pending.requestId!)) ||
        revision <
          (pending?.minimumRevision ?? pane.props._refresh_revision ?? 0)
      )
        return;
      const hasContent = ["_data", "_svg", "_plotly_json_str", "_url"].some(
        (key) => Object.hasOwn(updates, key),
      );
      if (
        pending === undefined &&
        Object.entries(updates).every(([key, value]) =>
          Object.is(Reflect.get(pane.props, key), value),
        )
      )
        return;
      const panes = copyPaneRecord(page.panes);
      const updatedPane = detachViewportPaneBinary(
        {
          ...pane,
          props: { ...pane.props, ...updates },
          refreshPending: hasContent ? undefined : pending,
        } as ViewportPane,
        pane,
      );
      panes[paneId] = updatedPane;
      let layout = page.layout;
      if (updatedPane.props.visible !== pane.props.visible) {
        if (updatedPane.props.visible) {
          const savedLayout = readLayout(page.pageId);
          layout = hasViewportPane(savedLayout, paneId)
            ? savedLayout
            : placeViewportPane(layout, paneId, null, "right");
        } else {
          layout = removeViewportPane(layout, paneId);
        }
        layout = reconcilePaneLayout(
          layout,
          panes,
          authoritativePanesByPage.get(pageId) ?? null,
        );
      }
      replacePage({ ...page, panes, layout });
    },

    removePane: (pageId, paneId) => {
      const page = streamedPage(pageId);
      if (page === undefined) return;
      const panes = copyPaneRecord(page.panes);
      delete panes[paneId];
      authoritativePanesByPage.get(pageId)?.delete(paneId);
      const layout = reconcilePaneLayout(
        removeViewportPane(page.layout, paneId),
        panes,
        authoritativePanesByPage.get(pageId) ?? null,
      );
      replacePage({ ...page, panes, layout });
    },

    setPaneSnapshot: (pageId, paneIds) => {
      const page = streamedPage(pageId);
      if (page === undefined) return;
      const firstSnapshot = authoritativePanesByPage.get(pageId) === null;
      const ids = new Set(paneIds);
      authoritativePanesByPage.set(pageId, ids);
      const panes = copyPaneRecord(page.panes);
      for (const paneId of Object.keys(panes)) {
        if (!ids.has(paneId)) delete panes[paneId];
      }
      const layout = reconcilePaneLayout(page.layout, panes, ids);
      // The first empty snapshot only establishes a newly declared page's
      // baseline. Keep any saved arrangement available for panes that are
      // declared immediately afterwards; later exact snapshots still prune
      // layouts after real removals.
      if (!(firstSnapshot && ids.size === 0)) persistLayout(pageId, layout);
      replacePage({ ...page, panes, layout });
    },

    commitUserLayout: (rawLayout) => {
      const state = store.get();
      const pageId = state.activePageId;
      if (pageId === null || !isViewportPageReady(state)) return;
      const page = state.pages[pageId];
      if (page === undefined) return;
      const layout = reconcilePaneLayout(
        normalizeViewportLayout(rawLayout),
        page.panes,
        authoritativePanesByPage.get(page.pageId) ?? null,
      );
      if (commitPageLayout(page, layout, true))
        replacePage({ ...page, layout });
    },
  };

  return { store, actions };
}

export type ViewportSession = ReturnType<typeof createViewportState>;

/** Own one viewport session and its initial persistence adapter per viewer. */
export function useViewportState(
  storage: ViewportLayoutStorage | null = browserStorage(),
): ViewportSession {
  return React.useState(() => createViewportState(storage))[0];
}
