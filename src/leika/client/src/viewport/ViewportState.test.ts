import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  MAX_LIVE_VIEWPORT_CONTENT_PANES,
  MAX_LIVE_VIEWPORT_VISER_PANES,
  MAX_VIEWPORT_SOURCE_CODE_UNITS,
} from "./viewportLimits";
import {
  VIEWPORT_ROOT_PANE_ID,
  collectViewportPaneIds,
  dropViewportPane,
} from "./layoutModel";
import { MAX_LAYOUT_ID_CODE_UNITS } from "../persistenceLimits";
import {
  ViewportActions,
  ViewportImageDeclaration,
  ViewportLayoutStorage,
  ViewportPageState,
  ViewportViserDeclaration,
  useViewportState,
  viewportLayoutStorageKey,
} from "./ViewportState";

const DEFAULT_PAGE_ID = "default";

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

class ReadOnlyStorage implements ViewportLayoutStorage {
  constructor(private readonly value: string) {}
  getItem(): string {
    return this.value;
  }
  setItem(): void {
    throw new Error("read only");
  }
}

function createViewportHarness(storage: ViewportLayoutStorage | null = null): {
  actions: HarnessActions;
  getState: () => ViewportPageState;
  viewportActions: ViewportActions;
  getViewportState: ReturnType<typeof useViewportState>["store"]["get"];
} {
  let viewport: ReturnType<typeof useViewportState> | undefined;
  function Harness(): React.ReactNode {
    viewport = useViewportState(storage);
    return null;
  }
  renderToStaticMarkup(React.createElement(Harness));
  if (viewport === undefined)
    throw new Error("Viewport harness did not render");
  const viewportActions = viewport.actions;
  const addDefaultPage = () =>
    viewportActions.addPage(DEFAULT_PAGE_ID, "Main", true);
  addDefaultPage();
  const actions: HarnessActions = {
    ...viewportActions,
    reset: () => {
      viewportActions.reset();
      addDefaultPage();
    },
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
  overrides: Partial<ViewportImageDeclaration> = {},
): ViewportImageDeclaration {
  return {
    page_id: DEFAULT_PAGE_ID,
    pane_id: paneId,
    props: {
      _data: null,
      _format: "png",
      title: paneId,
      visible: true,
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
  overrides: Partial<ViewportViserDeclaration> = {},
): ViewportViserDeclaration {
  return {
    page_id: DEFAULT_PAGE_ID,
    pane_id: paneId,
    props: {
      _url: null,
      _port: 8080,
      title: paneId,
      visible: true,
    },
    placement: "right",
    relative_to: VIEWPORT_ROOT_PANE_ID,
    equalize_group: [],
    ...overrides,
  };
}

describe("useViewportState hidden root lifecycle", () => {
  it("uses a blank root only while there are no visible content panes", () => {
    const { actions, getState } = createViewportHarness();
    expect(collectViewportPaneIds(getState().layout)).toEqual([
      VIEWPORT_ROOT_PANE_ID,
    ]);

    actions.addImagePane(imageDeclaration("first"));
    expect(collectViewportPaneIds(getState().layout)).toEqual(["first"]);

    actions.addImagePane(imageDeclaration("second"));
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
    actions.addImagePane(imageDeclaration("image"));
    actions.updatePane("image", { visible: false });
    expect(collectViewportPaneIds(getState().layout)).toEqual([
      VIEWPORT_ROOT_PANE_ID,
    ]);
    actions.updatePane("image", { visible: true });
    expect(collectViewportPaneIds(getState().layout)).toEqual(["image"]);
  });

  it("updates content without remount-oriented layout state", () => {
    const { actions, getState } = createViewportHarness();
    actions.addImagePane(imageDeclaration("image"));
    const layout = getState().layout;
    actions.updatePane("image", { title: "updated", fit: "fill" });
    const pane = getState().panes.image;
    expect(pane?.kind === "image" ? pane.props.title : undefined).toBe(
      "updated",
    );
    expect(pane?.kind === "image" ? pane.props.fit : undefined).toBe("fill");
    expect(getState().layout).toBe(layout);
  });

  it("detaches retained image bytes from the websocket frame backing store", () => {
    const { actions, getState } = createViewportHarness();
    const frame = new ArrayBuffer(1024 * 1024);
    const oneByte = new Uint8Array(frame, 128, 1) as Uint8Array<ArrayBuffer>;
    actions.addImagePane(
      imageDeclaration("image", {
        props: {
          _data: oneByte,
          _format: "png",
          title: "image",
          visible: false,
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
  });

  it("re-points a viser pane between port and URL targets", () => {
    const { actions, getState } = createViewportHarness();
    actions.addViserPane(viserDeclaration("viser"));
    expect(collectViewportPaneIds(getState().layout)).toEqual(["viser"]);
    const layout = getState().layout;
    const url = "http://viser.example.com:9000";
    actions.updatePane("viser", { _url: url, _port: null });
    const pane = getState().panes.viser;
    expect(pane?.kind === "viser" ? pane.props._url : undefined).toBe(url);
    expect(pane?.kind === "viser" ? pane.props._port : undefined).toBeNull();
    expect(getState().layout).toBe(layout);
  });

  it("rejects empty and reserved pane IDs", () => {
    const { actions, getState } = createViewportHarness();
    actions.addImagePane(imageDeclaration(""));
    actions.addImagePane(imageDeclaration(VIEWPORT_ROOT_PANE_ID));
    actions.removePane(VIEWPORT_ROOT_PANE_ID);
    expect(Object.keys(getState().panes)).toEqual([VIEWPORT_ROOT_PANE_ID]);
  });

  it("rejects malformed placement and equalization identifiers", () => {
    const { actions, getState } = createViewportHarness();
    actions.addImagePane(
      imageDeclaration("bad-relative", { relative_to: "__proto__" }),
    );
    actions.addImagePane(
      imageDeclaration("bad-group", { equalize_group: ["same", "same"] }),
    );
    actions.addImagePane(
      imageDeclaration("self-group", { equalize_group: ["self-group"] }),
    );
    actions.addImagePane(
      imageDeclaration("huge-group", {
        equalize_group: ["x".repeat(MAX_LAYOUT_ID_CODE_UNITS + 1)],
      }),
    );
    expect(Object.keys(getState().panes)).toEqual([VIEWPORT_ROOT_PANE_ID]);
  });
});

describe("useViewportState persistence", () => {
  it("namespaces saved layouts by server and workspace", () => {
    const storage = new MemoryStorage();
    const { actions, getState } = createViewportHarness(storage);
    actions.setPersistenceServer("ws://server");
    actions.setPersistenceWorkspace("workspace-a");
    actions.addImagePane(imageDeclaration("a"));
    actions.addImagePane(imageDeclaration("b"));
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
    actions.addImagePane(imageDeclaration("a"));
    actions.addImagePane(imageDeclaration("b"));
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

  it("rejects malformed workspace IDs before constructing storage keys", () => {
    const storage = new MemoryStorage();
    const { actions } = createViewportHarness(storage);
    actions.setPersistenceServer("ws://server");
    actions.setPersistenceWorkspace("x".repeat(MAX_LAYOUT_ID_CODE_UNITS + 1));
    actions.setPersistenceWorkspace("__proto__");
    expect(storage.values.size).toBe(0);
    expect(
      actions.preflightMessageBatch([
        {
          type: "WorkspaceConfigurationMessage",
          workspace_id: "",
        },
      ]),
    ).toContain("workspace identifier");
  });

  it("restores a readable layout even when normalization cannot be written back", () => {
    const storage = new ReadOnlyStorage(
      JSON.stringify({
        version: 1,
        root: { type: "pane", pane_id: "image" },
      }),
    );
    const { actions, getState } = createViewportHarness(storage);
    actions.setPersistenceServer("ws://server");
    actions.setPersistenceWorkspace("read-only");
    expect(collectViewportPaneIds(getState().layout)).toEqual([
      VIEWPORT_ROOT_PANE_ID,
      "image",
    ]);
  });
});

describe("useViewportState snapshot reconciliation", () => {
  it("treats every snapshot as exact authority", () => {
    const { actions, getState } = createViewportHarness();
    actions.addImagePane(imageDeclaration("keep"));
    actions.addImagePane(imageDeclaration("remove"));
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
    actions.addImagePane(imageDeclaration("future"));
    expect(collectViewportPaneIds(getState().layout)).toEqual(["future"]);
  });

  it("rejects duplicate, root, reserved, and oversized snapshot IDs", () => {
    const { actions, getState } = createViewportHarness();
    actions.addImagePane(imageDeclaration("keep"));
    for (const paneIds of [
      ["keep", "keep"],
      [VIEWPORT_ROOT_PANE_ID],
      ["constructor"],
      ["x".repeat(MAX_LAYOUT_ID_CODE_UNITS + 1)],
    ]) {
      actions.setPaneSnapshot(paneIds);
      expect(getState().panes.keep?.kind).toBe("image");
    }
  });

  it("bounds authoritative and declared pane owners and releases capacity", () => {
    const { actions, getState } = createViewportHarness();
    const paneIds = Array.from(
      { length: MAX_LIVE_VIEWPORT_CONTENT_PANES },
      (_, index) => `pane-${index}`,
    );
    actions.setPaneSnapshot(paneIds);

    const overflow = imageDeclaration("overflow");
    overflow.props.visible = false;
    actions.addImagePane(overflow);
    expect(getState().panes.overflow).toBeUndefined();

    // An oversized replacement snapshot is rejected atomically and cannot
    // make its extra ID admissible.
    actions.setPaneSnapshot([...paneIds, "overflow"]);
    actions.addImagePane(overflow);
    expect(getState().panes.overflow).toBeUndefined();

    actions.removePane(paneIds[0]);
    actions.addImagePane(overflow);
    expect(getState().panes.overflow?.kind).toBe("image");
  });

  it("counts hidden panes and releases live owner capacity on reset", () => {
    const { actions, getState } = createViewportHarness();
    for (let index = 0; index < MAX_LIVE_VIEWPORT_CONTENT_PANES; index += 1) {
      const declaration = imageDeclaration("hidden-" + index);
      declaration.props.visible = false;
      actions.addImagePane(declaration);
    }
    actions.addImagePane(imageDeclaration("overflow"));
    expect(getState().panes.overflow).toBeUndefined();

    actions.resetPanes();
    actions.addImagePane(imageDeclaration("reconnected"));
    expect(getState().panes.reconnected?.kind).toBe("image");
  });

  it("bounds retained Viser iframe owners independently", () => {
    const { actions, getState } = createViewportHarness();
    for (let index = 0; index < MAX_LIVE_VIEWPORT_VISER_PANES; index += 1) {
      actions.addViserPane(viserDeclaration("viser-" + index));
    }
    actions.addViserPane(viserDeclaration("viser-overflow"));
    expect(getState().panes["viser-overflow"]).toBeUndefined();
    expect(
      Object.values(getState().panes).filter((pane) => pane.kind === "viser"),
    ).toHaveLength(MAX_LIVE_VIEWPORT_VISER_PANES);
  });

  it("reserves replacement source delta before committing pane updates", () => {
    const { actions, getState } = createViewportHarness();
    const source = "x".repeat(MAX_VIEWPORT_SOURCE_CODE_UNITS / 2 - 1);
    const declaration = (paneId: string) => ({
      page_id: DEFAULT_PAGE_ID,
      pane_id: paneId,
      placement: "right" as const,
      relative_to: VIEWPORT_ROOT_PANE_ID,
      equalize_group: [],
      props: {
        _plotly_json_str: source,
        _theme_templates: "",
        title: "x",
        visible: false,
      },
    });
    actions.addPlotlyPane(declaration("first"));
    actions.addPlotlyPane(declaration("second"));
    actions.updatePane("second", { title: "xx" });

    const second = getState().panes.second;
    expect(second?.kind === "plotly" ? second.props.title : undefined).toBe(
      "x",
    );
  });
});

describe("useViewportState pages", () => {
  it("scopes identical pane IDs, updates, removals, and snapshots by page", () => {
    const { viewportActions, getViewportState } = createViewportHarness();
    viewportActions.addPage("analysis", "Analysis", false);
    viewportActions.addImagePane(imageDeclaration("shared"));
    viewportActions.addImagePane(
      imageDeclaration("shared", { page_id: "analysis" }),
    );

    viewportActions.updatePane("analysis", "shared", { title: "Result" });
    const defaultPane = getViewportState().pages.default.panes.shared;
    const analysisPane = getViewportState().pages.analysis.panes.shared;
    expect(
      defaultPane?.kind === "image" ? defaultPane.props.title : undefined,
    ).toBe("shared");
    expect(
      analysisPane?.kind === "image" ? analysisPane.props.title : undefined,
    ).toBe("Result");

    viewportActions.setPaneSnapshot("analysis", []);
    expect(getViewportState().pages.analysis.panes.shared).toBeUndefined();
    expect(getViewportState().pages.default.panes.shared?.kind).toBe("image");

    viewportActions.removePane(DEFAULT_PAGE_ID, "shared");
    expect(getViewportState().pages.default.panes.shared).toBeUndefined();
  });

  it("switches locally, preserves each layout, and advances the gesture epoch", () => {
    const { viewportActions, getViewportState } = createViewportHarness();
    viewportActions.addPage("analysis", "Analysis", false);
    viewportActions.addImagePane(imageDeclaration("live"));
    viewportActions.addImagePane(
      imageDeclaration("chart", { page_id: "analysis" }),
    );
    const before = getViewportState().interactionEpoch;

    viewportActions.setActivePage("analysis");
    expect(getViewportState().activePageId).toBe("analysis");
    expect(getViewportState().interactionEpoch).toBe(before + 1);
    expect(
      collectViewportPaneIds(getViewportState().pages.analysis.layout),
    ).toEqual(["chart"]);
    expect(
      collectViewportPaneIds(getViewportState().pages.default.layout),
    ).toEqual(["live"]);

    viewportActions.updatePane(DEFAULT_PAGE_ID, "live", {
      title: "Updated while inactive",
    });
    viewportActions.setActivePage(DEFAULT_PAGE_ID);
    const pane = getViewportState().pages.default.panes.live;
    expect(pane.kind === "image" ? pane.props.title : undefined).toBe(
      "Updated while inactive",
    );
  });

  it("uses independent layout keys, migrates v2 for only the default page, and restores selection", () => {
    const storage = new MemoryStorage();
    const legacy = {
      version: 1,
      root: { type: "pane", pane_id: "legacy" },
    };
    storage.values.set(
      "leika.viewport.layout.v2:ws://server:workspace",
      JSON.stringify(legacy),
    );
    const { actions, viewportActions, getViewportState } =
      createViewportHarness(storage);
    actions.setPersistenceServer("ws://server");
    actions.setPersistenceWorkspace("workspace");
    viewportActions.addPage("analysis", "Analysis", false);

    expect(
      collectViewportPaneIds(getViewportState().pages.default.layout),
    ).toEqual([VIEWPORT_ROOT_PANE_ID, "legacy"]);
    expect(
      collectViewportPaneIds(getViewportState().pages.analysis.layout),
    ).toEqual([VIEWPORT_ROOT_PANE_ID]);
    expect(
      storage.values.has(
        viewportLayoutStorageKey("ws://server", "workspace", DEFAULT_PAGE_ID),
      ),
    ).toBe(true);

    // A live client sees PageCreate + the page's empty baseline before the
    // caller can add panes. That bootstrap must not erase the saved position.
    viewportActions.setPaneSnapshot(DEFAULT_PAGE_ID, []);
    expect(
      collectViewportPaneIds(getViewportState().pages.default.layout),
    ).toEqual([VIEWPORT_ROOT_PANE_ID]);
    viewportActions.addImagePane(imageDeclaration("legacy"));
    expect(
      collectViewportPaneIds(getViewportState().pages.default.layout),
    ).toEqual(["legacy"]);

    viewportActions.setActivePage("analysis");
    actions.resetPanes();
    viewportActions.addPage("analysis", "Analysis", false);
    expect(getViewportState().activePageId).toBe("analysis");
  });

  it("enforces live-pane limits across pages rather than per page", () => {
    const { viewportActions, getViewportState } = createViewportHarness();
    viewportActions.addPage("analysis", "Analysis", false);
    for (let index = 0; index < MAX_LIVE_VIEWPORT_CONTENT_PANES; index += 1) {
      const declaration = imageDeclaration(`pane-${index}`, {
        page_id: index % 2 === 0 ? DEFAULT_PAGE_ID : "analysis",
      });
      declaration.props.visible = false;
      viewportActions.addImagePane(declaration);
    }
    viewportActions.addImagePane(
      imageDeclaration("overflow", { page_id: "analysis" }),
    );
    expect(getViewportState().pages.analysis.panes.overflow).toBeUndefined();
  });
});
