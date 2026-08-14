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
  ViewportState,
  ViewportViserDeclaration,
  useViewportState,
  viewportLayoutStorageKey,
} from "./ViewportState";

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
  actions: ViewportActions;
  getState: () => ViewportState;
} {
  let viewport: ReturnType<typeof useViewportState> | undefined;
  function Harness(): React.ReactNode {
    viewport = useViewportState(storage);
    return null;
  }
  renderToStaticMarkup(React.createElement(Harness));
  if (viewport === undefined)
    throw new Error("Viewport harness did not render");
  return { actions: viewport.actions, getState: viewport.store.get };
}

function imageDeclaration(
  paneId: string,
  overrides: Partial<ViewportImageDeclaration> = {},
): ViewportImageDeclaration {
  return {
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
