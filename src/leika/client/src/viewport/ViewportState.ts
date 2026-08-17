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
import { commonRendererStringWithinLimit } from "../guiLimits";
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

export interface ViewportImageDeclaration {
  page_id: string;
  pane_id: string;
  props: ViewportImageProps;
  placement: ViewportPanePlacement;
  relative_to: string;
  equalize_group: readonly string[];
}

export interface ViewportMatplotlibDeclaration {
  page_id: string;
  pane_id: string;
  props: ViewportMatplotlibProps;
  placement: ViewportPanePlacement;
  relative_to: string;
  equalize_group: readonly string[];
}

export interface ViewportPlotlyDeclaration {
  page_id: string;
  pane_id: string;
  props: ViewportPlotlyProps;
  placement: ViewportPanePlacement;
  relative_to: string;
  equalize_group: readonly string[];
}

export interface ViewportViserDeclaration {
  page_id: string;
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
  addPage: (pageId: string, name: string, isDefault: boolean) => void;
  updatePage: (pageId: string, name: string) => void;
  setActivePage: (pageId: string) => void;
  finishPageCatalog: (pageIds: readonly string[]) => void;
  beginPageSubscription: (pageId: string, generation: number) => void;
  beginPageStream: (pageId: string, generation: number) => void;
  finishPageStream: (pageId: string, generation: number) => void;
  addImagePane: (message: ViewportImageDeclaration) => void;
  addMatplotlibPane: (message: ViewportMatplotlibDeclaration) => void;
  addPlotlyPane: (message: ViewportPlotlyDeclaration) => void;
  addViserPane: (message: ViewportViserDeclaration) => void;
  updatePane: (
    pageId: string,
    paneId: string,
    updates: ViewportPaneUpdates,
  ) => void;
  removePane: (pageId: string, paneId: string) => void;
  setPaneSnapshot: (pageId: string, paneIds: readonly string[]) => void;
  commitUserLayout: (layout: ViewportLayout) => void;
  /** Pure admission for viewport state owned by one original wire frame. */
  preflightMessageBatch: (messages: readonly Message[]) => string | null;
  /** Admit a wire frame, evicting inactive warm pages only under pressure. */
  prepareMessageBatch: (messages: readonly Message[]) => string | null;
}

export interface ViewportLayoutStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const STORAGE_KEY_PREFIX = "leika.viewport.layout.v3:";
const LEGACY_STORAGE_KEY_PREFIX = "leika.viewport.layout.v2:";
const ACTIVE_PAGE_STORAGE_KEY_PREFIX = "leika.viewport.active-page.v1:";

export const MAX_VIEWPORT_PAGES = 128;

export function viewportLayoutStorageKey(
  serverUrl: string,
  workspaceId: string,
  pageId = "default",
): string {
  return STORAGE_KEY_PREFIX + JSON.stringify([serverUrl, workspaceId, pageId]);
}

export function legacyViewportLayoutStorageKey(
  serverUrl: string,
  workspaceId: string,
): string {
  return LEGACY_STORAGE_KEY_PREFIX + serverUrl + ":" + workspaceId;
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
  return {
    version: 1,
    root: { type: "pane", pane_id: VIEWPORT_ROOT_PANE_ID },
  };
}

export function initialViewportPanes(): Record<string, ViewportPane> {
  const panes = Object.create(null) as Record<string, ViewportPane>;
  panes[VIEWPORT_ROOT_PANE_ID] = {
    kind: "root",
    paneId: VIEWPORT_ROOT_PANE_ID,
    visible: true,
  };
  return panes;
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

type PageProjection = {
  panes: Map<string, ViewportContentPane>;
  authoritativePaneIds: Set<string> | null;
  isDefault: boolean;
  name: string;
};

function pageNameIsValid(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    commonRendererStringWithinLimit(value)
  );
}

/** Per-viewer page catalog, pane registries, and browser-owned layout store. */
export function useViewportState(
  storage: ViewportLayoutStorage | null = browserStorage(),
): {
  store: Store<ViewportState>;
  actions: ViewportActions;
} {
  const store = React.useMemo(() => createStore(initialState()), []);
  const persistenceServerRef = React.useRef<string | null>(null);
  const persistenceWorkspaceRef = React.useRef<string | null>(null);
  const preferredActivePageIdRef = React.useRef<string | null>(null);
  const authoritativePaneIdsRef = React.useRef(
    new Map<string, Set<string> | null>(),
  );
  const contentPaneCountRef = React.useRef(0);

  const actions = React.useMemo<ViewportActions>(() => {
    const layoutKey = (pageId: string): string | null => {
      const server = persistenceServerRef.current;
      const workspace = persistenceWorkspaceRef.current;
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

    const readLayout = (pageId: string, isDefault: boolean): ViewportLayout => {
      const key = layoutKey(pageId);
      if (storage === null || key === null) return initialViewportLayout();
      let serialized: string | null = null;
      let layout: ViewportLayout;
      try {
        serialized = storage.getItem(key);
        if (serialized === null && isDefault) {
          const server = persistenceServerRef.current;
          const workspace = persistenceWorkspaceRef.current;
          if (server !== null && workspace !== null) {
            serialized = storage.getItem(
              legacyViewportLayoutStorageKey(server, workspace),
            );
          }
        }
        if (serialized === null) return initialViewportLayout();
        layout = normalizeViewportLayout(parseBoundedPersistedJson(serialized));
      } catch {
        return initialViewportLayout();
      }
      try {
        storage.setItem(key, JSON.stringify(layout));
      } catch {
        // A read-only/full store must not discard a layout already read.
      }
      return layout;
    };

    const persistActivePage = (pageId: string): void => {
      const server = persistenceServerRef.current;
      const workspace = persistenceWorkspaceRef.current;
      if (storage === null || server === null || workspace === null) return;
      try {
        storage.setItem(
          activeViewportPageStorageKey(server, workspace),
          pageId,
        );
      } catch {
        // Selection persistence is best-effort, like layout persistence.
      }
    };

    const contentPanesFromPage = (
      page: ViewportPageState | null,
    ): ViewportContentPane[] =>
      page === null
        ? []
        : Object.values(page.panes).filter(
            (pane): pane is ViewportContentPane => pane.kind !== "root",
          );

    const clearCatalogPageModels = (
      pages: Record<string, ViewportPageState>,
    ): Record<string, ViewportPageState> => {
      const cleared = Object.create(null) as Record<string, ViewportPageState>;
      for (const [pageId, page] of Object.entries(pages)) {
        authoritativePaneIdsRef.current.set(pageId, null);
        cleared[pageId] = { ...page, panes: initialViewportPanes() };
      }
      return cleared;
    };

    const recountContentPanes = (
      pages: Record<string, ViewportPageState>,
      warmPage: ViewportPageState | null,
      transitionPage: ViewportPageState | null,
    ): void => {
      const models = [
        ...Object.values(pages),
        ...(warmPage === null ? [] : [warmPage]),
        ...(transitionPage === null ? [] : [transitionPage]),
      ];
      const seen = new Set<ViewportPageState>();
      contentPaneCountRef.current = models.reduce((count, page) => {
        if (seen.has(page)) return count;
        seen.add(page);
        return count + contentPanesFromPage(page).length;
      }, 0);
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

    const addContentPane = (
      message: {
        page_id: string;
        pane_id: string;
        placement: ViewportPanePlacement;
        relative_to: string;
        equalize_group: readonly string[];
      },
      pane: ViewportContentPane,
    ): void => {
      const state = store.get();
      const page = state.pages[message.page_id];
      const paneId = message.pane_id;
      if (
        page === undefined ||
        paneId === VIEWPORT_ROOT_PANE_ID ||
        paneId.length === 0
      )
        return;
      const alreadyDeclared = Object.hasOwn(page.panes, paneId);
      const authoritativePaneIds =
        authoritativePaneIdsRef.current.get(page.pageId) ?? null;
      if (
        (!alreadyDeclared &&
          contentPaneCountRef.current >= MAX_LIVE_VIEWPORT_CONTENT_PANES) ||
        (authoritativePaneIds !== null &&
          !authoritativePaneIds.has(paneId) &&
          [...authoritativePaneIdsRef.current.values()].reduce(
            (count, ids) => count + (ids?.size ?? 0),
            0,
          ) >= MAX_LIVE_VIEWPORT_CONTENT_PANES)
      )
        return;

      authoritativePaneIds?.add(paneId);
      const panes = copyPaneRecord(page.panes);
      panes[paneId] = detachViewportPaneBinary(pane);
      if (!alreadyDeclared) contentPaneCountRef.current += 1;

      let layout = page.layout;
      if (!pane.props.visible) {
        layout = removeViewportPane(layout, paneId);
      } else if (!hasViewportPane(layout, paneId)) {
        const savedLayout = readLayout(page.pageId, page.isDefault);
        if (hasViewportPane(savedLayout, paneId)) {
          // A page declaration and its initial empty snapshot can reach an
          // already-connected browser before Python declares that page's
          // panes. Recover each arriving pane from the browser-owned layout
          // instead of replacing that layout with creation-time hints.
          layout = savedLayout;
        } else {
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
      }
      layout = reconcilePaneLayout(layout, panes, authoritativePaneIds);
      replacePage({ ...page, panes, layout });
    };

    const projectMessageBatch = (
      messages: readonly Message[],
      includeWarmPage: boolean,
      includeTransitionPage: boolean,
    ): string | null => {
      const current = store.get();
      const retainedPages = [
        ...(includeWarmPage && current.warmPage !== null
          ? [current.warmPage]
          : []),
        ...(includeTransitionPage && current.transitionPage !== null
          ? [current.transitionPage]
          : []),
      ];
      const retainedPageRefs = new Set<ViewportPageState>();
      const retainedPanes = retainedPages.flatMap((page) => {
        if (retainedPageRefs.has(page)) return [];
        retainedPageRefs.add(page);
        return contentPanesFromPage(page);
      });
      const pages = new Map<string, PageProjection>();
      for (const pageId of current.pageOrder) {
        const page = current.pages[pageId];
        const panes = new Map<string, ViewportContentPane>();
        for (const pane of Object.values(page.panes)) {
          if (pane.kind !== "root") panes.set(pane.paneId, pane);
        }
        const authoritative = authoritativePaneIdsRef.current.get(pageId);
        pages.set(pageId, {
          panes,
          authoritativePaneIds:
            authoritative === undefined
              ? null
              : authoritative === null
                ? null
                : new Set(authoritative),
          isDefault: page.isDefault,
          name: page.name,
        });
      }
      const reject = (detail: string) =>
        "Connection frame violates viewport safety limits: " + detail;
      const allPanes = (): ViewportContentPane[] => [
        ...retainedPanes,
        ...[...pages.values()].flatMap((page) => [...page.panes.values()]),
      ];
      const authoritativeCount = (): number =>
        [...pages.values()].reduce(
          (count, page) => count + (page.authoritativePaneIds?.size ?? 0),
          0,
        );

      for (const message of messages) {
        if (message.type === "PageCreateMessage") {
          if (
            !isBoundedLayoutId(message.page_id) ||
            !pageNameIsValid(message.name) ||
            typeof message.is_default !== "boolean" ||
            pages.has(message.page_id) ||
            pages.size >= MAX_VIEWPORT_PAGES ||
            (message.is_default &&
              [...pages.values()].some((page) => page.isDefault))
          )
            return reject("page declaration is invalid");
          pages.set(message.page_id, {
            panes: new Map(),
            authoritativePaneIds: null,
            isDefault: message.is_default,
            name: message.name,
          });
          continue;
        }
        if (message.type === "PageUpdateMessage") {
          const page = pages.get(message.page_id);
          if (page === undefined || !pageNameIsValid(message.name))
            return reject("page update is invalid");
          page.name = message.name;
          continue;
        }
        if (message.type === "PageCatalogMessage") {
          if (
            message.page_ids.length !== pages.size ||
            message.page_ids.some(
              (pageId, index) => [...pages.keys()][index] !== pageId,
            )
          )
            return reject("page catalog does not match its declarations");
          continue;
        }

        const declaration = contentPaneFromMessage(message);
        if (declaration !== null) {
          if (
            message.type !== "ViewportImageMessage" &&
            message.type !== "ViewportMatplotlibMessage" &&
            message.type !== "ViewportPlotlyMessage" &&
            message.type !== "ViewportViserMessage"
          )
            return reject("pane declaration type is invalid");
          const page = pages.get(message.page_id);
          if (
            page === undefined ||
            !isBoundedLayoutId(message.relative_to) ||
            !equalizeGroupIsValid(message.pane_id, message.equalize_group)
          )
            return reject("pane page or placement identifiers are invalid");
          if (
            !isBoundedLayoutId(declaration.paneId) ||
            declaration.paneId === VIEWPORT_ROOT_PANE_ID ||
            !panePropsHaveValidShape(declaration)
          )
            return reject("pane declaration is invalid");
          if (
            !page.panes.has(declaration.paneId) &&
            allPanes().length >= MAX_LIVE_VIEWPORT_CONTENT_PANES
          )
            return reject("live pane owner limit exceeded");
          if (
            page.authoritativePaneIds !== null &&
            !page.authoritativePaneIds.has(declaration.paneId) &&
            authoritativeCount() >= MAX_LIVE_VIEWPORT_CONTENT_PANES
          )
            return reject("authoritative pane owner limit exceeded");
          page.panes.set(declaration.paneId, declaration);
          page.authoritativePaneIds?.add(declaration.paneId);
          if (!viewportPanesWithinAggregateLimits(allPanes()))
            return reject("pane source, renderer, or iframe budget exceeded");
          continue;
        }

        if (
          message.type === "ViewportPaneUpdateMessage" ||
          message.type === "ViewportPaneRemoveMessage" ||
          message.type === "ViewportPaneSnapshotMessage"
        ) {
          const page = pages.get(message.page_id);
          if (page === undefined)
            return reject("pane lifecycle references an unknown page");
          if (message.type === "ViewportPaneUpdateMessage") {
            if (!isBoundedLayoutId(message.pane_id))
              return reject("pane update identifier is invalid");
            const previous = page.panes.get(message.pane_id);
            if (previous === undefined) continue;
            const candidate = {
              ...previous,
              props: { ...previous.props, ...message.updates },
            } as ViewportContentPane;
            page.panes.set(message.pane_id, candidate);
            if (
              !panePropsHaveValidShape(candidate) ||
              !viewportPanesWithinAggregateLimits(allPanes())
            )
              return reject("pane update violates its schema or budget");
          } else if (message.type === "ViewportPaneRemoveMessage") {
            if (!isBoundedLayoutId(message.pane_id))
              return reject("pane removal identifier is invalid");
            page.panes.delete(message.pane_id);
            page.authoritativePaneIds?.delete(message.pane_id);
          } else {
            if (message.pane_ids.length > MAX_LIVE_VIEWPORT_CONTENT_PANES)
              return reject("pane snapshot owner limit exceeded");
            const ids = new Set<string>();
            for (const paneId of message.pane_ids) {
              if (
                !isBoundedLayoutId(paneId) ||
                paneId === VIEWPORT_ROOT_PANE_ID ||
                ids.has(paneId)
              )
                return reject("pane snapshot identifiers are invalid");
              ids.add(paneId);
            }
            page.authoritativePaneIds = ids;
            for (const paneId of page.panes.keys()) {
              if (!ids.has(paneId)) page.panes.delete(paneId);
            }
            if (authoritativeCount() > MAX_LIVE_VIEWPORT_CONTENT_PANES)
              return reject("aggregate pane snapshot owner limit exceeded");
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

    type CacheAdmission = {
      failure: string | null;
      evictWarmPage: boolean;
      evictTransitionPage: boolean;
    };

    const cacheAdmission = (messages: readonly Message[]): CacheAdmission => {
      const current = store.get();
      const failure = projectMessageBatch(messages, true, true);
      if (failure === null)
        return {
          failure: null,
          evictWarmPage: false,
          evictTransitionPage: false,
        };
      if (
        current.warmPage !== null &&
        projectMessageBatch(messages, false, true) === null
      )
        return {
          failure: null,
          evictWarmPage: true,
          evictTransitionPage: false,
        };
      if (
        current.transitionPage !== null &&
        projectMessageBatch(messages, true, false) === null
      )
        return {
          failure: null,
          evictWarmPage: false,
          evictTransitionPage: true,
        };
      if (
        current.warmPage !== null &&
        current.transitionPage !== null &&
        projectMessageBatch(messages, false, false) === null
      )
        return {
          failure: null,
          evictWarmPage: true,
          evictTransitionPage: true,
        };
      return {
        failure,
        evictWarmPage: false,
        evictTransitionPage: false,
      };
    };

    let pendingAdmissionMessages: readonly Message[] | null = null;
    let pendingAdmissionState: ViewportState | null = null;
    let pendingAdmission: CacheAdmission | null = null;

    const preflightMessageBatch = (
      messages: readonly Message[],
    ): string | null => {
      pendingAdmissionMessages = messages;
      pendingAdmissionState = store.get();
      pendingAdmission = cacheAdmission(messages);
      return pendingAdmission.failure;
    };

    const prepareMessageBatch = (
      messages: readonly Message[],
    ): string | null => {
      const admission =
        pendingAdmissionMessages === messages &&
        pendingAdmissionState === store.get() &&
        pendingAdmission !== null
          ? pendingAdmission
          : cacheAdmission(messages);
      pendingAdmissionMessages = null;
      pendingAdmissionState = null;
      pendingAdmission = null;
      if (admission.failure !== null) return admission.failure;
      if (!admission.evictWarmPage && !admission.evictTransitionPage)
        return null;

      const current = store.get();
      let warmPage = admission.evictWarmPage ? null : current.warmPage;
      let transitionPage = admission.evictTransitionPage
        ? null
        : current.transitionPage;
      if (
        transitionPage === null &&
        current.transitionPage !== null &&
        warmPage !== null
      ) {
        transitionPage = warmPage;
        warmPage = null;
      }
      const displayPageId =
        transitionPage?.pageId ??
        (current.pageStream?.ready === true &&
        current.pageStream.pageId === current.activePageId
          ? current.activePageId
          : null);
      recountContentPanes(current.pages, warmPage, transitionPage);
      store.set({
        warmPage,
        transitionPage,
        displayPageId,
        interactionEpoch:
          displayPageId === current.displayPageId
            ? current.interactionEpoch
            : current.interactionEpoch + 1,
      });
      return null;
    };

    const directMessage = (type: Message["type"], value: object): Message =>
      ({ type, ...value }) as Message;
    const admitDirect = (message: Message): boolean => {
      const failure = prepareMessageBatch([message]);
      if (failure === null) return true;
      console.error(failure);
      return false;
    };
    const clearPages = (): void => {
      authoritativePaneIdsRef.current.clear();
      contentPaneCountRef.current = 0;
      store.set(initialState(store.get().interactionEpoch + 1));
    };

    return {
      reset: clearPages,
      resetPanes: clearPages,

      setPersistenceServer: (serverUrl) => {
        if (persistenceServerRef.current === serverUrl) return;
        persistenceServerRef.current = serverUrl;
        persistenceWorkspaceRef.current = null;
        preferredActivePageIdRef.current = null;
        clearPages();
      },

      setPersistenceWorkspace: (workspaceId) => {
        const serverUrl = persistenceServerRef.current;
        if (serverUrl === null || !isBoundedLayoutId(workspaceId)) return;
        if (persistenceWorkspaceRef.current === workspaceId) return;
        persistenceWorkspaceRef.current = workspaceId;
        preferredActivePageIdRef.current = null;
        if (storage !== null) {
          try {
            const pageId = storage.getItem(
              activeViewportPageStorageKey(serverUrl, workspaceId),
            );
            if (pageId !== null && isBoundedLayoutId(pageId)) {
              preferredActivePageIdRef.current = pageId;
            }
          } catch {
            // Inaccessible storage simply starts on the default page.
          }
        }
        clearPages();
      },

      addPage: (pageId, name, isDefault) => {
        if (
          !admitDirect(
            directMessage("PageCreateMessage", {
              page_id: pageId,
              name,
              is_default: isDefault,
            }),
          )
        )
          return;
        const state = store.get();
        const page: ViewportPageState = {
          pageId,
          name,
          isDefault,
          panes: initialViewportPanes(),
          layout: readLayout(pageId, isDefault),
        };
        authoritativePaneIdsRef.current.set(pageId, null);
        store.set({
          pages: { ...state.pages, [pageId]: page },
          pageOrder: [...state.pageOrder, pageId],
          catalogReady: false,
        });
      },

      updatePage: (pageId, name) => {
        if (
          !admitDirect(
            directMessage("PageUpdateMessage", { page_id: pageId, name }),
          )
        )
          return;
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
        if (
          !admitDirect(
            directMessage("PageCatalogMessage", { page_ids: pageIds }),
          )
        )
          return;
        const state = store.get();
        const preferred = preferredActivePageIdRef.current;
        const defaultPageId = state.pageOrder.find(
          (pageId) => state.pages[pageId]?.isDefault,
        );
        const activePageId =
          preferred !== null && pageIds.includes(preferred)
            ? preferred
            : state.activePageId !== null &&
                pageIds.includes(state.activePageId)
              ? state.activePageId
              : (defaultPageId ?? pageIds[0] ?? null);
        const activeChanged = activePageId !== state.activePageId;
        const pages = activeChanged
          ? clearCatalogPageModels(state.pages)
          : state.pages;
        const warmPage = activeChanged ? null : state.warmPage;
        const transitionPage = activeChanged ? null : state.transitionPage;
        if (activeChanged) recountContentPanes(pages, warmPage, transitionPage);
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
          !Number.isSafeInteger(generation) ||
          generation < 0 ||
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
        recountContentPanes(pages, warmPage, transitionPage);
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
        recountContentPanes(state.pages, warmPage, null);
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
        recountContentPanes(pages, warmPage, transitionPage);
        preferredActivePageIdRef.current = pageId;
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

      updatePane: (pageId, paneId, updates) => {
        if (
          !admitDirect(
            directMessage("ViewportPaneUpdateMessage", {
              page_id: pageId,
              pane_id: paneId,
              updates,
            }),
          )
        )
          return;
        const page = store.get().pages[pageId];
        const pane = page?.panes[paneId];
        if (page === undefined || pane === undefined || pane.kind === "root")
          return;
        const panes = copyPaneRecord(page.panes);
        const updatedPane = detachViewportPaneBinary({
          ...pane,
          props: { ...pane.props, ...updates },
        } as ViewportContentPane);
        panes[paneId] = updatedPane;
        let layout = page.layout;
        if (updatedPane.props.visible !== pane.props.visible) {
          if (updatedPane.props.visible) {
            const savedLayout = readLayout(page.pageId, page.isDefault);
            if (hasViewportPane(savedLayout, paneId)) {
              layout = savedLayout;
            } else {
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
            }
          } else {
            layout = removeViewportPane(layout, paneId);
          }
          layout = reconcilePaneLayout(
            layout,
            panes,
            authoritativePaneIdsRef.current.get(pageId) ?? null,
          );
        }
        replacePage({ ...page, panes, layout });
      },

      removePane: (pageId, paneId) => {
        if (
          paneId === VIEWPORT_ROOT_PANE_ID ||
          !admitDirect(
            directMessage("ViewportPaneRemoveMessage", {
              page_id: pageId,
              pane_id: paneId,
            }),
          )
        )
          return;
        const page = store.get().pages[pageId];
        if (page === undefined) return;
        const panes = copyPaneRecord(page.panes);
        if (Object.hasOwn(panes, paneId)) contentPaneCountRef.current -= 1;
        delete panes[paneId];
        authoritativePaneIdsRef.current.get(pageId)?.delete(paneId);
        const layout = reconcilePaneLayout(
          removeViewportPane(page.layout, paneId),
          panes,
          authoritativePaneIdsRef.current.get(pageId) ?? null,
          paneId,
        );
        replacePage({ ...page, panes, layout });
      },

      setPaneSnapshot: (pageId, paneIds) => {
        if (
          !admitDirect(
            directMessage("ViewportPaneSnapshotMessage", {
              page_id: pageId,
              pane_ids: paneIds,
            }),
          )
        )
          return;
        const page = store.get().pages[pageId];
        if (page === undefined) return;
        const firstSnapshot =
          authoritativePaneIdsRef.current.get(pageId) === null;
        const ids = new Set(paneIds);
        authoritativePaneIdsRef.current.set(pageId, ids);
        const panes = copyPaneRecord(page.panes);
        for (const paneId of Object.keys(panes)) {
          if (paneId !== VIEWPORT_ROOT_PANE_ID && !ids.has(paneId)) {
            delete panes[paneId];
            contentPaneCountRef.current -= 1;
          }
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
        const stream = state.pageStream;
        if (
          state.activePageId === null ||
          state.displayPageId !== state.activePageId ||
          state.transitionPage !== null ||
          stream === null ||
          stream.pageId !== state.activePageId ||
          !stream.ready
        )
          return;
        const page = state.pages[state.activePageId];
        if (page === undefined) return;
        const layout = reconcilePaneLayout(
          normalizeViewportLayout(rawLayout),
          page.panes,
          authoritativePaneIdsRef.current.get(page.pageId) ?? null,
        );
        if (commitPageLayout(page, layout, true))
          replacePage({ ...page, layout });
      },
      preflightMessageBatch,
      prepareMessageBatch,
    };
  }, [storage, store]);

  return { store, actions };
}
