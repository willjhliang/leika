import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  VIEWPORT_ROOT_PANE_ID,
  collectViewportPaneIds,
  dropViewportPane,
} from "./layoutModel";
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
});
