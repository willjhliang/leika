import { describe, expect, it } from "vitest";

import {
  VIEWPORT_ROOT_PANE_ID,
  collectViewportPaneIds,
  dropViewportPane,
} from "./layoutModel";
import {
  activeViewportPageStorageKey,
  isViewportPageReady,
  ViewportActions,
  ViewportLayoutStorage,
  ViewportPageState,
  ViewportPaneCreateMessage,
  createViewportState,
  viewportLayoutStorageKey,
} from "./ViewportState";

const DEFAULT_PAGE_ID = "default";

type ImageMessage = Extract<
  ViewportPaneCreateMessage,
  { type: "ViewportImageMessage" }
>;
type ViserMessage = Extract<
  ViewportPaneCreateMessage,
  { type: "ViewportViserMessage" }
>;

type HarnessActions = Omit<
  ViewportActions,
  "updatePane" | "removePane" | "setPaneSnapshot"
> & {
  updatePane: (
    paneId: string,
    updates: Parameters<ViewportActions["updatePane"]>[2],
  ) => void;
  removePane: (paneId: string) => void;
  setPaneSnapshot: (paneIds: readonly string[]) => void;
};

class MemoryStorage implements ViewportLayoutStorage {
  readonly values = new Map<string, string>();
  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

function createEmptyViewportHarness(
  storage: ViewportLayoutStorage | null = null,
): {
  viewportActions: ViewportActions;
  getViewportState: ReturnType<typeof createViewportState>["store"]["get"];
} {
  const viewport = createViewportState(storage);
  return {
    viewportActions: viewport.actions,
    getViewportState: viewport.store.get,
  };
}

function createViewportHarness(storage: ViewportLayoutStorage | null = null): {
  actions: HarnessActions;
  getState: () => ViewportPageState;
  viewportActions: ViewportActions;
  getViewportState: ReturnType<typeof createViewportState>["store"]["get"];
} {
  const viewport = createViewportState(storage);
  const viewportActions = viewport.actions;
  // Pane messages apply to the page stream the browser subscribed to.
  const addDefaultPage = () => {
    viewportActions.addPage(DEFAULT_PAGE_ID, "Main", true);
    viewportActions.finishPageCatalog([DEFAULT_PAGE_ID]);
    viewportActions.beginPageSubscription(DEFAULT_PAGE_ID, 0);
    viewportActions.beginPageStream(DEFAULT_PAGE_ID, 0);
  };
  addDefaultPage();
  const actions: HarnessActions = {
    ...viewportActions,
    resetPanes: () => {
      viewportActions.resetPanes();
      addDefaultPage();
    },
    setPersistenceWorkspace: (workspaceId) => {
      viewportActions.setPersistenceWorkspace(workspaceId);
      addDefaultPage();
    },
    updatePane: (paneId, updates) =>
      viewportActions.updatePane(DEFAULT_PAGE_ID, paneId, updates),
    removePane: (paneId) => viewportActions.removePane(DEFAULT_PAGE_ID, paneId),
    setPaneSnapshot: (paneIds) =>
      viewportActions.setPaneSnapshot(DEFAULT_PAGE_ID, paneIds),
  };
  const getViewportState = viewport.store.get;
  const getState = (): ViewportPageState => {
    const page = getViewportState().pages[DEFAULT_PAGE_ID];
    if (page === undefined) throw new Error("Default page is absent");
    return page;
  };
  return { actions, getState, viewportActions, getViewportState };
}

function imageDeclaration(
  paneId: string,
  overrides: Partial<ImageMessage> = {},
): ImageMessage {
  return {
    type: "ViewportImageMessage",
    page_id: DEFAULT_PAGE_ID,
    pane_id: paneId,
    props: {
      _data: new Uint8Array(0),
      _format: "png",
      title: paneId,
      visible: true,
      loading: false,
      fit: "fit",
    },
    placement: "right",
    relative_to: VIEWPORT_ROOT_PANE_ID,
    equalize_group: [],
    ...overrides,
  };
}

function viserDeclaration(
  paneId: string,
  overrides: Partial<ViserMessage> = {},
): ViserMessage {
  return {
    type: "ViewportViserMessage",
    page_id: DEFAULT_PAGE_ID,
    pane_id: paneId,
    props: {
      _url: "/_leika/viser/1/",
      title: paneId,
      visible: true,
      loading: false,
    },
    placement: "right",
    relative_to: VIEWPORT_ROOT_PANE_ID,
    equalize_group: [],
    ...overrides,
  };
}

describe("createViewportState hidden root lifecycle", () => {
  it("uses a blank root only while there are no visible content panes", () => {
    const { actions, getState } = createViewportHarness();
    expect(collectViewportPaneIds(getState().layout)).toEqual([
      VIEWPORT_ROOT_PANE_ID,
    ]);

    actions.addPane(imageDeclaration("first"));
    expect(collectViewportPaneIds(getState().layout)).toEqual(["first"]);

    actions.addPane(imageDeclaration("second"));
    expect(collectViewportPaneIds(getState().layout)).toEqual([
      "first",
      "second",
    ]);

    actions.removePane("first");
    actions.removePane("second");
    expect(collectViewportPaneIds(getState().layout)).toEqual([
      VIEWPORT_ROOT_PANE_ID,
    ]);
  });

  it("removes hidden panes and deterministically restores them", () => {
    const { actions, getState } = createViewportHarness();
    actions.addPane(imageDeclaration("image"));
    actions.updatePane("image", { visible: false });
    expect(collectViewportPaneIds(getState().layout)).toEqual([
      VIEWPORT_ROOT_PANE_ID,
    ]);
    actions.updatePane("image", { visible: true });
    expect(collectViewportPaneIds(getState().layout)).toEqual(["image"]);
  });

  it("updates content without remount-oriented layout state", () => {
    const { actions, getState } = createViewportHarness();
    actions.addPane(imageDeclaration("image"));
    const layout = getState().layout;
    actions.updatePane("image", {
      title: "updated",
      fit: "fill",
      loading: "Indexing ABC · 129k episodes",
    });
    const pane = getState().panes.image;
    expect(pane?.kind === "image" ? pane.props.title : undefined).toBe(
      "updated",
    );
    expect(pane?.kind === "image" ? pane.props.fit : undefined).toBe("fill");
    expect(pane?.kind === "image" ? pane.props.loading : undefined).toBe(
      "Indexing ABC · 129k episodes",
    );
    expect(getState().layout).toBe(layout);
  });

  it("detaches retained image bytes from the websocket frame backing store", () => {
    const { actions, getState } = createViewportHarness();
    const frame = new ArrayBuffer(1024 * 1024);
    const oneByte = new Uint8Array(frame, 128, 1) as Uint8Array<ArrayBuffer>;
    actions.addPane(
      imageDeclaration("image", {
        props: {
          _data: oneByte,
          _format: "png",
          title: "image",
          visible: false,
          loading: false,
          fit: "fit",
        },
      }),
    );

    const pane = getState().panes.image;
    expect(pane?.kind).toBe("image");
    if (pane?.kind !== "image" || pane.props._data === null) return;
    expect(pane.props._data).not.toBe(oneByte);
    expect(pane.props._data.byteLength).toBe(1);
    expect(pane.props._data.buffer.byteLength).toBe(1);

    actions.updatePane("image", { title: "renamed", fit: "fill" });
    const renamed = getState().panes.image;
    if (renamed?.kind !== "image") throw new Error("Expected image");
    expect(renamed.props._data).toBe(pane.props._data);
    oneByte[0] = 99;
    expect(renamed.props._data?.[0]).toBe(0);

    const unchangedPage = getState();
    actions.updatePane("image", { title: "renamed", fit: "fill" });
    expect(getState()).toBe(unchangedPage);

    actions.updatePane("image", { _data: oneByte });
    const replaced = getState().panes.image;
    if (replaced?.kind !== "image" || replaced.props._data === null)
      throw new Error("Expected image bytes");
    expect(replaced.props._data).not.toBe(pane.props._data);
    expect(replaced.props._data).not.toBe(oneByte);
    expect(replaced.props._data.buffer.byteLength).toBe(1);
    expect(replaced.props._data[0]).toBe(99);
    oneByte[0] = 42;
    expect(replaced.props._data[0]).toBe(99);
  });

  it("re-points a viser pane between proxied and URL targets", () => {
    const { actions, getState } = createViewportHarness();
    actions.addPane(viserDeclaration("viser"));
    expect(collectViewportPaneIds(getState().layout)).toEqual(["viser"]);
    const layout = getState().layout;
    const url = "http://viser.example.com:9000";
    actions.updatePane("viser", { _url: url });
    const pane = getState().panes.viser;
    expect(pane?.kind === "viser" ? pane.props._url : undefined).toBe(url);
    expect(getState().layout).toBe(layout);
  });
});

describe("createViewportState persistence", () => {
  it("namespaces saved layouts by server and workspace", () => {
    const storage = new MemoryStorage();
    const { actions, getState } = createViewportHarness(storage);
    actions.setPersistenceServer("ws://server");
    actions.setPersistenceWorkspace("workspace-a");
    actions.beginPageSubscription(DEFAULT_PAGE_ID, 1);
    actions.beginPageStream(DEFAULT_PAGE_ID, 1);
    actions.addPane(imageDeclaration("a"));
    actions.addPane(imageDeclaration("b"));
    actions.finishPageStream(DEFAULT_PAGE_ID, 1);
    actions.commitUserLayout(
      dropViewportPane(getState().layout, "a", "b", "center"),
    );
    expect(collectViewportPaneIds(getState().layout)).toEqual(["b", "a"]);
    expect(
      storage.values.has(
        viewportLayoutStorageKey("ws://server", "workspace-a"),
      ),
    ).toBe(true);

    actions.setPersistenceWorkspace("workspace-b");
    expect(collectViewportPaneIds(getState().layout)).toEqual([
      VIEWPORT_ROOT_PANE_ID,
    ]);
    actions.setPersistenceWorkspace("workspace-a");
    expect(collectViewportPaneIds(getState().layout)).toEqual([
      VIEWPORT_ROOT_PANE_ID,
      "b",
      "a",
    ]);
    expect(getState().panes.a).toBeUndefined();
    actions.addPane(imageDeclaration("a"));
    actions.addPane(imageDeclaration("b"));
    actions.setPaneSnapshot(["a", "b"]);
    expect(collectViewportPaneIds(getState().layout)).toEqual(["b", "a"]);
  });

  it("falls back safely for malformed stored data", () => {
    const storage = new MemoryStorage();
    storage.values.set(
      viewportLayoutStorageKey("ws://server", "broken"),
      "not json",
    );
    const { actions, getState } = createViewportHarness(storage);
    actions.setPersistenceServer("ws://server");
    actions.setPersistenceWorkspace("broken");
    expect(collectViewportPaneIds(getState().layout)).toEqual([
      VIEWPORT_ROOT_PANE_ID,
    ]);
  });
});

describe("createViewportState snapshot reconciliation", () => {
  it("treats every snapshot as exact authority", () => {
    const { actions, getState } = createViewportHarness();
    actions.addPane(imageDeclaration("keep"));
    actions.addPane(imageDeclaration("remove"));
    actions.setPaneSnapshot(["keep"]);
    expect(getState().panes.keep?.kind).toBe("image");
    expect(getState().panes.remove).toBeUndefined();
    expect(collectViewportPaneIds(getState().layout)).toEqual(["keep"]);
  });

  it("does not invent panes that have not hydrated", () => {
    const { actions, getState } = createViewportHarness();
    actions.setPaneSnapshot(["future"]);
    expect(getState().panes.future).toBeUndefined();
    expect(collectViewportPaneIds(getState().layout)).toEqual([
      VIEWPORT_ROOT_PANE_ID,
    ]);
    actions.addPane(imageDeclaration("future"));
    expect(collectViewportPaneIds(getState().layout)).toEqual(["future"]);
  });
});

describe("createViewportState pages", () => {
  it("keeps the first page behind the catalog barrier and restores the preferred page", () => {
    const storage = new MemoryStorage();
    storage.values.set(
      activeViewportPageStorageKey("ws://server", "workspace"),
      "analysis",
    );
    const { viewportActions, getViewportState } =
      createEmptyViewportHarness(storage);
    viewportActions.setPersistenceServer("ws://server");
    viewportActions.setPersistenceWorkspace("workspace");
    viewportActions.addPage(DEFAULT_PAGE_ID, "Main", true);
    viewportActions.addPage("analysis", "Analysis", false);

    expect(getViewportState()).toMatchObject({
      activePageId: null,
      catalogReady: false,
      pageStream: null,
    });

    viewportActions.finishPageCatalog([DEFAULT_PAGE_ID, "analysis"]);
    expect(getViewportState()).toMatchObject({
      activePageId: "analysis",
      catalogReady: true,
      pageStream: null,
    });
  });

  it("falls back from an absent preference to the default, then to the first page", () => {
    const storage = new MemoryStorage();
    storage.values.set(
      activeViewportPageStorageKey("ws://server", "workspace"),
      "removed",
    );
    const preferredMissing = createEmptyViewportHarness(storage);
    preferredMissing.viewportActions.setPersistenceServer("ws://server");
    preferredMissing.viewportActions.setPersistenceWorkspace("workspace");
    preferredMissing.viewportActions.addPage("first", "First", false);
    preferredMissing.viewportActions.addPage(DEFAULT_PAGE_ID, "Main", true);
    preferredMissing.viewportActions.finishPageCatalog([
      "first",
      DEFAULT_PAGE_ID,
    ]);
    expect(preferredMissing.getViewportState().activePageId).toBe(
      DEFAULT_PAGE_ID,
    );

    const noDefault = createEmptyViewportHarness();
    noDefault.viewportActions.addPage("first", "First", false);
    noDefault.viewportActions.addPage("second", "Second", false);
    noDefault.viewportActions.finishPageCatalog(["first", "second"]);
    expect(noDefault.getViewportState().activePageId).toBe("first");
  });

  it("promotes a matching ready stream into a displayable cached model", () => {
    const { viewportActions, getViewportState } = createViewportHarness();
    expect(isViewportPageReady(getViewportState())).toBe(false);
    viewportActions.beginPageSubscription(DEFAULT_PAGE_ID, 7);
    viewportActions.beginPageStream(DEFAULT_PAGE_ID, 7);
    viewportActions.addPane(imageDeclaration("main"));

    expect(getViewportState()).toMatchObject({
      displayPageId: null,
      transitionPage: null,
      warmPage: null,
    });

    viewportActions.finishPageStream(DEFAULT_PAGE_ID, 7);
    expect(isViewportPageReady(getViewportState())).toBe(true);

    const state = getViewportState();
    expect(state.displayPageId).toBe(DEFAULT_PAGE_ID);
    expect(state.transitionPage).toBeNull();
    expect(state.warmPage).toBeNull();
    expect(state.pages.default.panes.main?.kind).toBe("image");
    expect(state.pageStream).toEqual({
      pageId: DEFAULT_PAGE_ID,
      generation: 7,
      accepting: true,
      ready: true,
    });
  });

  it("retains one displayed snapshot across reconnects and reconciles a fresh replay", () => {
    const { viewportActions: actions, getViewportState } =
      createEmptyViewportHarness();
    actions.setPersistenceServer("ws://server");
    actions.setPersistenceWorkspace("workspace");
    actions.addPage(DEFAULT_PAGE_ID, "Main", true);
    actions.finishPageCatalog([DEFAULT_PAGE_ID]);
    actions.beginPageSubscription(DEFAULT_PAGE_ID, 1);
    actions.beginPageStream(DEFAULT_PAGE_ID, 1);
    actions.addPane(imageDeclaration("keep"));
    actions.addPane(imageDeclaration("removed"));
    actions.finishPageStream(DEFAULT_PAGE_ID, 1);
    const displayed = getViewportState().pages.default;

    actions.reconnect();
    actions.reconnect();
    expect(getViewportState()).toMatchObject({
      pages: {},
      activePageId: DEFAULT_PAGE_ID,
      displayPageId: DEFAULT_PAGE_ID,
      catalogReady: false,
      pageStream: null,
      warmPage: null,
    });
    expect(getViewportState().transitionPage).toBe(displayed);
    expect(isViewportPageReady(getViewportState())).toBe(false);
    actions.setPersistenceWorkspace("workspace");
    actions.addPage(DEFAULT_PAGE_ID, "Main", true);
    actions.finishPageCatalog([DEFAULT_PAGE_ID]);
    actions.beginPageSubscription(DEFAULT_PAGE_ID, 2);
    actions.beginPageStream(DEFAULT_PAGE_ID, 2);
    actions.addPane(imageDeclaration("keep"));
    actions.addPane(imageDeclaration("added"));
    expect(getViewportState().transitionPage).toBe(displayed);
    actions.finishPageStream(DEFAULT_PAGE_ID, 1);
    expect(isViewportPageReady(getViewportState())).toBe(false);
    actions.finishPageStream(DEFAULT_PAGE_ID, 2);
    expect(getViewportState().transitionPage).toBeNull();
    expect(getViewportState().pages.default.panes.keep?.kind).toBe("image");
    expect(getViewportState().pages.default.panes.added?.kind).toBe("image");
    expect(getViewportState().pages.default.panes.removed).toBeUndefined();
    expect(isViewportPageReady(getViewportState())).toBe(true);
  });

  it.each(["server", "workspace", "page"])(
    "discards reconnect content when its %s disappears",
    (owner) => {
      const { viewportActions: actions, getViewportState } =
        createEmptyViewportHarness();
      actions.setPersistenceServer("ws://server");
      actions.setPersistenceWorkspace("workspace");
      actions.addPage(DEFAULT_PAGE_ID, "Main", true);
      actions.finishPageCatalog([DEFAULT_PAGE_ID]);
      actions.beginPageSubscription(DEFAULT_PAGE_ID, 1);
      actions.beginPageStream(DEFAULT_PAGE_ID, 1);
      actions.addPane(imageDeclaration("old"));
      actions.finishPageStream(DEFAULT_PAGE_ID, 1);
      actions.reconnect();
      if (owner === "server") actions.setPersistenceServer("ws://different");
      else if (owner === "workspace")
        actions.setPersistenceWorkspace("different");
      else {
        actions.addPage("different", "Different", true);
        actions.finishPageCatalog(["different"]);
      }
      expect(getViewportState().transitionPage).toBeNull();
      expect(getViewportState().displayPageId).toBeNull();
    },
  );

  it("keeps the outgoing page visible until an uncached target is ready", () => {
    const { viewportActions, getViewportState } = createViewportHarness();
    viewportActions.addPage("analysis", "Analysis", false);
    viewportActions.finishPageCatalog([DEFAULT_PAGE_ID, "analysis"]);
    viewportActions.beginPageSubscription(DEFAULT_PAGE_ID, 1);
    viewportActions.beginPageStream(DEFAULT_PAGE_ID, 1);
    viewportActions.addPane(imageDeclaration("main"));
    viewportActions.finishPageStream(DEFAULT_PAGE_ID, 1);
    expect(isViewportPageReady(getViewportState())).toBe(true);

    viewportActions.setActivePage("analysis");
    expect(isViewportPageReady(getViewportState())).toBe(false);
    expect(getViewportState()).toMatchObject({
      activePageId: "analysis",
      displayPageId: DEFAULT_PAGE_ID,
    });
    viewportActions.beginPageSubscription("analysis", 2);
    viewportActions.beginPageStream("analysis", 2);
    viewportActions.addPane(imageDeclaration("chart", { page_id: "analysis" }));
    const transitioning = getViewportState();
    expect(transitioning.displayPageId).toBe(DEFAULT_PAGE_ID);
    expect(transitioning.transitionPage?.pageId).toBe(DEFAULT_PAGE_ID);
    expect(transitioning.transitionPage?.panes.main?.kind).toBe("image");
    expect(transitioning.pages.default.panes.main).toBeUndefined();
    expect(isViewportPageReady(transitioning)).toBe(false);

    viewportActions.finishPageStream("analysis", 2);
    expect(isViewportPageReady(getViewportState())).toBe(true);
    const ready = getViewportState();
    expect(ready.activePageId).toBe("analysis");
    expect(ready.displayPageId).toBe("analysis");
    expect(ready.transitionPage).toBeNull();
    expect(ready.warmPage?.pageId).toBe(DEFAULT_PAGE_ID);
    expect(ready.warmPage?.panes.main?.kind).toBe("image");
    expect(ready.pages.analysis.panes.chart?.kind).toBe("image");
  });

  it("displays cached targets immediately and preserves cache during refresh", () => {
    const { viewportActions, getViewportState } = createViewportHarness();
    viewportActions.addPage("analysis", "Analysis", false);
    viewportActions.finishPageCatalog([DEFAULT_PAGE_ID, "analysis"]);
    viewportActions.beginPageSubscription(DEFAULT_PAGE_ID, 1);
    viewportActions.beginPageStream(DEFAULT_PAGE_ID, 1);
    viewportActions.addPane(imageDeclaration("main"));
    viewportActions.finishPageStream(DEFAULT_PAGE_ID, 1);
    viewportActions.setActivePage("analysis");
    viewportActions.beginPageSubscription("analysis", 2);
    viewportActions.beginPageStream("analysis", 2);
    viewportActions.addPane(imageDeclaration("chart", { page_id: "analysis" }));
    viewportActions.finishPageStream("analysis", 2);
    expect(isViewportPageReady(getViewportState())).toBe(true);

    viewportActions.setActivePage(DEFAULT_PAGE_ID);
    expect(getViewportState()).toMatchObject({
      activePageId: DEFAULT_PAGE_ID,
      displayPageId: DEFAULT_PAGE_ID,
    });
    expect(getViewportState().pageStream).toBeNull();
    expect(isViewportPageReady(getViewportState())).toBe(false);

    viewportActions.beginPageSubscription(DEFAULT_PAGE_ID, 3);
    viewportActions.beginPageStream(DEFAULT_PAGE_ID, 3);
    const refreshing = getViewportState();
    expect(isViewportPageReady(refreshing)).toBe(false);
    expect(refreshing.displayPageId).toBe(DEFAULT_PAGE_ID);
    expect(refreshing.transitionPage?.pageId).toBe(DEFAULT_PAGE_ID);
    expect(refreshing.transitionPage?.panes.main?.kind).toBe("image");
    expect(refreshing.warmPage?.pageId).toBe("analysis");
    expect(refreshing.warmPage?.panes.chart?.kind).toBe("image");
    expect(refreshing.pages.default.panes.main).toBeUndefined();
    expect(refreshing.pages.analysis.panes.chart).toBeUndefined();

    viewportActions.finishPageStream(DEFAULT_PAGE_ID, 3);
    expect(isViewportPageReady(getViewportState())).toBe(true);
  });

  it("evicts an older warm model for a cold third page", () => {
    const { viewportActions, getViewportState } = createViewportHarness();
    viewportActions.addPage("analysis", "Analysis", false);
    viewportActions.addPage("diagnostics", "Diagnostics", false);
    viewportActions.finishPageCatalog([
      DEFAULT_PAGE_ID,
      "analysis",
      "diagnostics",
    ]);
    viewportActions.beginPageSubscription(DEFAULT_PAGE_ID, 1);
    viewportActions.beginPageStream(DEFAULT_PAGE_ID, 1);
    viewportActions.addPane(imageDeclaration("main"));
    viewportActions.finishPageStream(DEFAULT_PAGE_ID, 1);
    viewportActions.setActivePage("analysis");
    viewportActions.beginPageSubscription("analysis", 2);
    viewportActions.beginPageStream("analysis", 2);
    viewportActions.addPane(imageDeclaration("chart", { page_id: "analysis" }));
    viewportActions.finishPageStream("analysis", 2);
    expect(getViewportState().displayPageId).toBe("analysis");
    expect(getViewportState().warmPage?.pageId).toBe(DEFAULT_PAGE_ID);
    expect(getViewportState().warmPage?.panes.main?.kind).toBe("image");

    viewportActions.setActivePage(DEFAULT_PAGE_ID);
    expect(getViewportState().transitionPage?.pageId).toBe(DEFAULT_PAGE_ID);
    expect(getViewportState().warmPage?.pageId).toBe("analysis");
    viewportActions.beginPageSubscription(DEFAULT_PAGE_ID, 3);
    viewportActions.beginPageStream(DEFAULT_PAGE_ID, 3);
    viewportActions.addPane(imageDeclaration("main"));
    viewportActions.finishPageStream(DEFAULT_PAGE_ID, 3);
    expect(getViewportState().displayPageId).toBe(DEFAULT_PAGE_ID);
    expect(getViewportState().warmPage?.pageId).toBe("analysis");

    viewportActions.setActivePage("diagnostics");
    viewportActions.beginPageSubscription("diagnostics", 4);
    const coldTransition = getViewportState();
    expect(coldTransition.displayPageId).toBe(DEFAULT_PAGE_ID);
    expect(coldTransition.transitionPage?.pageId).toBe(DEFAULT_PAGE_ID);
    expect(coldTransition.transitionPage?.panes.main?.kind).toBe("image");
    expect(coldTransition.warmPage).toBeNull();
    expect(Object.keys(coldTransition.pages.analysis.panes)).toEqual([
      VIEWPORT_ROOT_PANE_ID,
    ]);

    viewportActions.beginPageStream("diagnostics", 4);
    viewportActions.addPane(
      imageDeclaration("diagnostic", { page_id: "diagnostics" }),
    );
    expect(getViewportState().displayPageId).toBe(DEFAULT_PAGE_ID);
    viewportActions.finishPageStream("diagnostics", 4);

    const state = getViewportState();
    expect(state.displayPageId).toBe("diagnostics");
    expect(state.transitionPage).toBeNull();
    expect(state.warmPage?.pageId).toBe(DEFAULT_PAGE_ID);
    expect(state.warmPage?.panes.main?.kind).toBe("image");
    expect(state.pages.default.panes.main).toBeUndefined();
    expect(state.pages.diagnostics.panes.diagnostic?.kind).toBe("image");
  });

  it("never promotes an abandoned partial refresh into the warm cache", () => {
    const { viewportActions, getViewportState } = createViewportHarness();
    viewportActions.addPage("analysis", "Analysis", false);
    viewportActions.finishPageCatalog([DEFAULT_PAGE_ID, "analysis"]);
    viewportActions.beginPageSubscription(DEFAULT_PAGE_ID, 1);
    viewportActions.beginPageStream(DEFAULT_PAGE_ID, 1);
    viewportActions.addPane(imageDeclaration("main"));
    viewportActions.finishPageStream(DEFAULT_PAGE_ID, 1);

    viewportActions.setActivePage("analysis");
    viewportActions.beginPageSubscription("analysis", 2);
    viewportActions.beginPageStream("analysis", 2);
    viewportActions.addPane(
      imageDeclaration("partial", { page_id: "analysis" }),
    );
    viewportActions.setActivePage(DEFAULT_PAGE_ID);
    viewportActions.finishPageStream("analysis", 2);
    viewportActions.setActivePage("analysis");
    viewportActions.beginPageSubscription("analysis", 3);

    const state = getViewportState();
    expect(state.activePageId).toBe("analysis");
    expect(state.displayPageId).toBe(DEFAULT_PAGE_ID);
    expect(state.transitionPage?.pageId).toBe(DEFAULT_PAGE_ID);
    expect(state.transitionPage?.panes.main?.kind).toBe("image");
    expect(state.warmPage).toBeNull();
    expect(state.pages.analysis.panes.partial).toBeUndefined();
  });

  it("opens and readies only the matching page-stream generation", () => {
    const { viewportActions, getViewportState } = createViewportHarness();
    viewportActions.beginPageSubscription(DEFAULT_PAGE_ID, 7);

    viewportActions.beginPageStream(DEFAULT_PAGE_ID, 6);
    viewportActions.beginPageStream("analysis", 7);
    viewportActions.finishPageStream(DEFAULT_PAGE_ID, 7);
    expect(getViewportState().pageStream).toEqual({
      pageId: DEFAULT_PAGE_ID,
      generation: 7,
      accepting: false,
      ready: false,
    });
    expect(isViewportPageReady(getViewportState())).toBe(false);

    viewportActions.beginPageStream(DEFAULT_PAGE_ID, 7);
    viewportActions.finishPageStream(DEFAULT_PAGE_ID, 6);
    viewportActions.finishPageStream("analysis", 7);
    expect(getViewportState().pageStream).toEqual({
      pageId: DEFAULT_PAGE_ID,
      generation: 7,
      accepting: true,
      ready: false,
    });
    expect(isViewportPageReady(getViewportState())).toBe(false);

    viewportActions.finishPageStream(DEFAULT_PAGE_ID, 7);
    expect(getViewportState().pageStream).toEqual({
      pageId: DEFAULT_PAGE_ID,
      generation: 7,
      accepting: true,
      ready: true,
    });
    expect(isViewportPageReady(getViewportState())).toBe(true);
  });

  it("applies pane messages only to the accepting page stream", () => {
    const { viewportActions, getViewportState } = createViewportHarness();
    viewportActions.addPage("analysis", "Analysis", false);
    viewportActions.addPane(imageDeclaration("shared"));
    viewportActions.addPane(
      imageDeclaration("shared", { page_id: "analysis" }),
    );
    viewportActions.updatePane("analysis", "shared", { title: "Result" });
    viewportActions.setPaneSnapshot("analysis", []);
    viewportActions.removePane("analysis", "shared");

    expect(getViewportState().pages.analysis.panes.shared).toBeUndefined();
    const defaultPane = getViewportState().pages.default.panes.shared;
    expect(
      defaultPane?.kind === "image" ? defaultPane.props.title : undefined,
    ).toBe("shared");

    // A newer subscription closes the stream until its own begin arrives, so
    // frames still in flight from the old generation are ignored.
    viewportActions.beginPageSubscription(DEFAULT_PAGE_ID, 1);
    viewportActions.addPane(imageDeclaration("stale"));
    viewportActions.beginPageStream(DEFAULT_PAGE_ID, 0);
    viewportActions.addPane(imageDeclaration("stale"));
    expect(getViewportState().pages.default.panes.stale).toBeUndefined();
    viewportActions.beginPageStream(DEFAULT_PAGE_ID, 1);
    viewportActions.addPane(imageDeclaration("current"));
    expect(getViewportState().pages.default.panes.current?.kind).toBe("image");
  });

  it("switches locally, preserves each layout, and advances the gesture epoch", () => {
    const { viewportActions, getViewportState } = createViewportHarness();
    viewportActions.addPage("analysis", "Analysis", false);
    viewportActions.finishPageCatalog([DEFAULT_PAGE_ID, "analysis"]);
    viewportActions.beginPageSubscription(DEFAULT_PAGE_ID, 1);
    viewportActions.beginPageStream(DEFAULT_PAGE_ID, 1);
    viewportActions.addPane(imageDeclaration("live"));
    viewportActions.finishPageStream(DEFAULT_PAGE_ID, 1);
    const before = getViewportState().interactionEpoch;

    viewportActions.setActivePage("analysis");
    expect(getViewportState().activePageId).toBe("analysis");
    expect(getViewportState().interactionEpoch).toBe(before + 1);
    viewportActions.beginPageSubscription("analysis", 2);
    viewportActions.beginPageStream("analysis", 2);
    viewportActions.addPane(imageDeclaration("chart", { page_id: "analysis" }));
    viewportActions.finishPageStream("analysis", 2);
    expect(
      collectViewportPaneIds(getViewportState().pages.analysis.layout),
    ).toEqual(["chart"]);
    expect(
      collectViewportPaneIds(getViewportState().pages.default.layout),
    ).toEqual(["live"]);

    viewportActions.setActivePage(DEFAULT_PAGE_ID);
    const pane = getViewportState().transitionPage?.panes.live;
    expect(pane?.kind === "image" ? pane.props.title : undefined).toBe("live");
  });

  it("uses independent layout keys and restores selection", () => {
    const storage = new MemoryStorage();
    storage.values.set(
      viewportLayoutStorageKey("ws://server", "workspace", DEFAULT_PAGE_ID),
      JSON.stringify({
        version: 1,
        root: { type: "pane", pane_id: "saved" },
      }),
    );
    const { actions, viewportActions, getViewportState } =
      createViewportHarness(storage);
    actions.setPersistenceServer("ws://server");
    actions.setPersistenceWorkspace("workspace");
    viewportActions.addPage("analysis", "Analysis", false);

    expect(
      collectViewportPaneIds(getViewportState().pages.default.layout),
    ).toEqual([VIEWPORT_ROOT_PANE_ID, "saved"]);
    expect(
      collectViewportPaneIds(getViewportState().pages.analysis.layout),
    ).toEqual([VIEWPORT_ROOT_PANE_ID]);

    // A live client sees PageCreate + the page's empty baseline before the
    // caller can add panes. That bootstrap must not erase the saved position.
    viewportActions.setPaneSnapshot(DEFAULT_PAGE_ID, []);
    expect(
      collectViewportPaneIds(getViewportState().pages.default.layout),
    ).toEqual([VIEWPORT_ROOT_PANE_ID]);
    viewportActions.addPane(imageDeclaration("saved"));
    expect(
      collectViewportPaneIds(getViewportState().pages.default.layout),
    ).toEqual(["saved"]);

    viewportActions.setActivePage("analysis");
    actions.resetPanes();
    viewportActions.addPage("analysis", "Analysis", false);
    viewportActions.finishPageCatalog([DEFAULT_PAGE_ID, "analysis"]);
    expect(getViewportState().activePageId).toBe("analysis");
  });

  it("ignores layout commits while a stale transition page is displayed", () => {
    const { viewportActions, getViewportState } = createViewportHarness();
    viewportActions.addPage("analysis", "Analysis", false);
    viewportActions.finishPageCatalog([DEFAULT_PAGE_ID, "analysis"]);
    viewportActions.beginPageSubscription(DEFAULT_PAGE_ID, 1);
    viewportActions.beginPageStream(DEFAULT_PAGE_ID, 1);
    viewportActions.addPane(imageDeclaration("a"));
    viewportActions.addPane(imageDeclaration("b"));
    viewportActions.finishPageStream(DEFAULT_PAGE_ID, 1);
    viewportActions.setActivePage("analysis");

    const before = getViewportState();
    const transitionLayout = before.transitionPage?.layout;
    if (transitionLayout === undefined)
      throw new Error("Expected a displayed transition page");
    const targetLayout = before.pages.analysis.layout;
    viewportActions.commitUserLayout(
      dropViewportPane(transitionLayout, "a", "b", "center"),
    );

    const after = getViewportState();
    expect(after).toBe(before);
    expect(after.transitionPage?.layout).toBe(transitionLayout);
    expect(after.pages.analysis.layout).toBe(targetLayout);
  });
});

describe("local selection refresh", () => {
  it("rejects old and superseded images until the latest request accompanies content", () => {
    const { actions, getState } = createViewportHarness();
    actions.addPane(imageDeclaration("camera"));
    actions.updatePane("camera", {
      _refresh_controls: ["dataset", "timeline"],
      _refresh_revision: 0,
      _refresh_requests: [],
      _data: new Uint8Array([1]),
    });
    // A real page has completed its subscription before it can be edited.
    actions.beginPageSubscription(DEFAULT_PAGE_ID, 1);
    actions.beginPageStream(DEFAULT_PAGE_ID, 1);
    actions.addPane(imageDeclaration("camera"));
    actions.updatePane("camera", {
      _refresh_controls: ["dataset", "timeline"],
      _refresh_revision: 0,
      _refresh_requests: [],
      _data: new Uint8Array([1]),
    });
    actions.finishPageStream(DEFAULT_PAGE_ID, 1);
    expect(actions.invalidateForInput("dataset", "first")).toBe(true);
    actions.updatePane("camera", {
      _data: new Uint8Array([2]),
      _refresh_revision: 0,
    });
    expect(getState().panes.camera).toMatchObject({
      refreshPending: { requestId: "first" },
      props: { _data: new Uint8Array([1]) },
    });
    actions.invalidateForInput("timeline", "last");
    actions.updatePane("camera", {
      _data: new Uint8Array([3]),
      _refresh_revision: 1,
      _refresh_requests: ["first"],
    });
    expect(getState().panes.camera).toMatchObject({
      refreshPending: { requestId: "last" },
    });
    actions.updatePane("camera", {
      _data: new Uint8Array([4]),
      _refresh_revision: 2,
      _refresh_requests: ["last"],
    });
    expect(getState().panes.camera).toHaveProperty("refreshPending", undefined);
    actions.updatePane("camera", {
      _data: new Uint8Array([5]),
      _refresh_revision: 1,
      _refresh_requests: ["first"],
    });
    expect(getState().panes.camera).toMatchObject({
      props: { _data: new Uint8Array([4]) },
    });
    expect(actions.invalidateForInput("unbound", "none")).toBe(false);
  });
});

it("replaces a video pane's source in place", () => {
  const { actions, getState } = createViewportHarness();
  const message = {
    type: "ViewportVideoMessage" as const,
    page_id: DEFAULT_PAGE_ID,
    pane_id: "videos",
    placement: "right" as const,
    relative_to: VIEWPORT_ROOT_PANE_ID,
    equalize_group: [],
    props: {
      _url: "/task.mp4",
      autoplay: true,
      loop: true,
      muted: true,
      controls: true,
      sync_group: null,
      fps: null,
      title: "Videos",
      visible: true,
      loading: false,
    },
  };
  actions.addPane(message);
  expect(getState().panes.videos.kind).toBe("video");
  actions.updatePane("videos", { _url: "/other.mp4" });
  const pane = getState().panes.videos;
  expect(pane.kind === "video" && pane.props._url).toBe("/other.mp4");
  actions.removePane("videos");
  expect(getState().panes.videos).toBeUndefined();
});

describe("replaceable pane content", () => {
  it("keeps a viewer arrangement while releasing the old renderer's props", () => {
    const { actions, getState } = createViewportHarness();
    actions.addPane(imageDeclaration("a"));
    actions.addPane(
      imageDeclaration("b", { relative_to: "a", placement: "bottom" }),
    );
    const layout = getState().layout;
    const empty = {
      ...imageDeclaration("a"),
      type: "ViewportEmptyMessage" as const,
      props: { title: "Preview", visible: true, loading: false },
    };
    actions.addPane(empty);
    expect(getState().layout).toEqual(layout);
    expect(getState().panes.a).toEqual({
      kind: "empty",
      paneId: "a",
      props: empty.props,
    });
    actions.addPane(viserDeclaration("a"));
    expect(getState().layout).toEqual(layout);
    expect(getState().panes.a.kind).toBe("viser");
    actions.addPane(empty);
    expect(getState().layout).toEqual(layout);
    expect(getState().panes.a).not.toHaveProperty("props._url");
    expect(getState().panes.a).not.toHaveProperty("props._data");
  });
});
