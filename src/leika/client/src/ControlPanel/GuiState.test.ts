import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  GuiFolderMessage,
  GuiFormMessage,
  GuiCheckboxMessage,
  GuiTextMessage,
  GuiImageMessage,
  GuiModalMessage,
  RegisterCommandMessage,
  Message,
  GuiTabGroupMessage,
  GuiTabMessage,
  GuiTabUpdateMessage,
} from "../WebsocketMessages";
import {
  MAX_BROWSER_LIVE_GUI_COMPONENTS,
  MAX_GUI_COMMON_STRING_CODE_UNITS,
  MAX_BROWSER_GUI_TEXT_CODE_UNITS,
} from "../guiLimits";
import { applyGuiConfigUpdate, useGuiState } from "./GuiState";

function createGuiStateHarness(): ReturnType<typeof useGuiState> {
  let gui: ReturnType<typeof useGuiState> | undefined;
  function Harness(): React.ReactNode {
    gui = useGuiState("ws://example.test");
    return null;
  }
  renderToStaticMarkup(React.createElement(Harness));
  if (gui === undefined) throw new Error("GUI state harness did not render");
  return gui;
}

function modal(uuid: string, order: number): GuiModalMessage {
  return { type: "GuiModalMessage", uuid, order, title: uuid };
}

function component(
  uuid: string,
  containerUuid: string,
  order: number,
): GuiFolderMessage {
  return {
    type: "GuiFolderMessage",
    uuid,
    container_uuid: containerUuid,
    props: {
      order,
      label: uuid,
      visible: true,
      expand_by_default: false,
    },
  };
}

function form(uuid: string, containerUuid: string): GuiFormMessage {
  return {
    type: "GuiFormMessage",
    uuid,
    container_uuid: containerUuid,
    props: { order: 0, label: uuid, visible: true, mini: false },
  };
}

function tabs(uuid: string, containerUuid: string): GuiTabGroupMessage {
  return {
    type: "GuiTabGroupMessage",
    uuid,
    container_uuid: containerUuid,
    props: {
      order: 0,
      visible: true,
      _tabs: [],
    },
  };
}

function tab(
  uuid: string,
  groupUuid: string,
  label = uuid,
  iconHtml: string | null = null,
): GuiTabMessage {
  return {
    type: "GuiTabMessage",
    uuid,
    group_uuid: groupUuid,
    label,
    icon_html: iconHtml,
  };
}

function tabUpdate(
  uuid: string,
  groupUuid: string,
  label: string,
  iconHtml: string | null = null,
): GuiTabUpdateMessage {
  return {
    type: "GuiTabUpdateMessage",
    uuid,
    group_uuid: groupUuid,
    label,
    icon_html: iconHtml,
  };
}

function checkbox(uuid: string, containerUuid: string): GuiCheckboxMessage {
  return {
    type: "GuiCheckboxMessage",
    uuid,
    value: false,
    container_uuid: containerUuid,
    props: {
      order: 0,
      label: uuid,
      hint: null,
      visible: true,
      disabled: false,
    },
  };
}

function text(
  uuid: string,
  containerUuid: string,
  value: string,
): GuiTextMessage {
  return {
    type: "GuiTextMessage",
    uuid,
    value,
    container_uuid: containerUuid,
    props: {
      order: 0,
      label: null,
      hint: null,
      visible: true,
      disabled: false,
      multiline: true,
      rows: null,
      editable: false,
      markdown: true,
      _source: value,
    },
  };
}

function command(
  uuid: string,
  label: string,
  description: string | null = null,
): RegisterCommandMessage {
  return {
    type: "RegisterCommandMessage",
    uuid,
    props: {
      label,
      description,
      hotkey: null,
      modifier: null,
      _icon_html: null,
      disabled: false,
    },
  };
}

describe("useGuiState", () => {
  it("keeps modals in protocol order", () => {
    const gui = createGuiStateHarness();
    gui.actions.addModal(modal("last", 20));
    gui.actions.addModal(modal("first", 5));
    gui.actions.addModal(modal("middle", 10));

    expect(gui.store.get().modals.map(({ uuid }) => uuid)).toEqual([
      "first",
      "middle",
      "last",
    ]);
  });

  it("replaces an existing modal instead of duplicating its UUID", () => {
    const gui = createGuiStateHarness();
    gui.actions.addModal(modal("shared", 20));
    gui.actions.addModal(modal("other", 10));
    gui.actions.addModal({ ...modal("shared", 5), title: "Replacement" });

    expect(gui.store.get().modals).toEqual([
      {
        type: "GuiModalMessage",
        uuid: "shared",
        order: 5,
        title: "Replacement",
      },
      modal("other", 10),
    ]);
  });

  it("moves a redeclared component out of its previous container", () => {
    const gui = createGuiStateHarness();
    gui.actions.addGuiBatch([
      component("left", "root", 0),
      component("right", "root", 1),
      component("shared", "left", 1),
    ]);
    gui.actions.addGui(component("shared", "right", 2));

    const state = gui.store.get();
    expect(state.guiUuidSetFromContainerUuid.left).toBeUndefined();
    expect(state.guiUuidSetFromContainerUuid.right).toEqual({ shared: true });
    expect(state.guiOrderFromUuid.shared).toBe(2);
    expect(gui.configStore.get("shared")?.container_uuid).toBe("right");
  });

  it("stores unusual safe IDs as ordinary own keys", () => {
    const gui = createGuiStateHarness();
    gui.actions.addGui(component("__proto__-component", "root", 1));

    let state = gui.store.get();
    expect(Object.getPrototypeOf(state.guiUuidSetFromContainerUuid)).toBeNull();
    const members = state.guiUuidSetFromContainerUuid.root!;
    expect(Object.getPrototypeOf(members)).toBeNull();
    expect(Object.hasOwn(members, "__proto__-component")).toBe(true);

    gui.actions.removeGui("__proto__-component");
    state = gui.store.get();
    expect(state.guiUuidSetFromContainerUuid.root).toEqual({});
  });

  it("clears the connection-owned workspace namespace on reset", () => {
    const gui = createGuiStateHarness();
    gui.store.set({ workspaceId: "previous-workspace" });

    gui.actions.resetGui();

    expect(gui.store.get().workspaceId).toBeNull();
  });

  it("treats removal of an unknown component as idempotent", () => {
    const gui = createGuiStateHarness();
    expect(() => gui.actions.removeGui("missing")).not.toThrow();
    expect(gui.store.get().guiUuidSetFromContainerUuid).toEqual({ root: {} });
  });

  it("purges every locally known descendant in one subtree removal", () => {
    const gui = createGuiStateHarness();
    gui.actions.addGuiBatch([
      component("folder", "root", 0),
      form("form", "folder"),
      tabs("tabs", "form"),
    ]);
    gui.actions.declareTab(tab("individual-tab", "tabs", "Individual"));
    gui.actions.addGuiBatch([
      component("nested", "individual-tab", 0),
      component("leaf", "nested", 0),
    ]);
    gui.actions.updateUploadState({
      componentId: "leaf",
      transferUuid: "transfer",
      uploadedBytes: 0,
      totalBytes: 1,
      filename: "leaf.bin",
    });

    gui.actions.removeGui("folder");

    expect(gui.configStore.size()).toBe(0);
    expect(gui.store.get().guiUuidSetFromContainerUuid).toEqual({ root: {} });
    expect(gui.store.get().guiOrderFromUuid).toEqual({});
    expect(gui.store.get().uploadsInProgress).toEqual({});
  });

  it("purges an exact-cap broad subtree without quadratic membership scans", () => {
    const gui = createGuiStateHarness();
    const declarations: GuiFolderMessage[] = [component("parent", "root", 0)];
    for (let index = 0; index < 4_095; index += 1) {
      const branch = "branch-" + index;
      declarations.push(component(branch, "parent", index));
      declarations.push(component("leaf-" + index, branch, index));
    }
    declarations.push(component("last", "parent", 4_096));
    expect(declarations).toHaveLength(MAX_BROWSER_LIVE_GUI_COMPONENTS);
    gui.actions.addGuiBatch(declarations);

    gui.actions.removeGui("parent");

    expect(gui.configStore.size()).toBe(0);
    expect(gui.store.get().guiUuidSetFromContainerUuid).toEqual({ root: {} });
  });

  it("uses server tombstones to purge descendants missing from local ancestry", () => {
    const gui = createGuiStateHarness();
    gui.actions.addGui(component("orphan", "root", 0));

    gui.actions.removeGui("missing-parent", ["orphan"]);

    expect(gui.configStore.get("orphan")).toBeUndefined();
    expect(gui.store.get().guiUuidSetFromContainerUuid).toEqual({ root: {} });
  });

  it("rejects duplicate, primary, and oversized removal tombstones", () => {
    const gui = createGuiStateHarness();
    const removal = (removedUuids: string[]): Message => ({
      type: "GuiRemoveMessage",
      uuid: "parent",
      removed_uuids: removedUuids,
      removed_tab_uuids: [],
    });
    expect(
      gui.actions.preflightMessageBatch([removal(["child", "child"])]),
    ).toContain("tombstones");
    expect(gui.actions.preflightMessageBatch([removal(["parent"])])).toContain(
      "tombstones",
    );
    expect(
      gui.actions.preflightMessageBatch([
        removal(Array.from({ length: 4_097 }, (_, index) => `child-${index}`)),
      ]),
    ).toContain("tombstones");
  });

  it("purges a modal's nested component subtree when the modal closes", () => {
    const gui = createGuiStateHarness();
    gui.actions.addModal(modal("modal", 0));
    gui.actions.addGuiBatch([
      component("folder", "modal", 0),
      component("leaf", "folder", 0),
    ]);

    gui.actions.removeModal("modal", ["folder", "leaf"]);

    expect(gui.store.get().modals).toEqual([]);
    expect(gui.configStore.size()).toBe(0);
    expect(gui.store.get().guiUuidSetFromContainerUuid).toEqual({ root: {} });
  });

  it("admits the page-wide GUI owner boundary in one state transaction", () => {
    const gui = createGuiStateHarness();
    let notifications = 0;
    gui.store.subscribe(() => {
      notifications += 1;
    });
    const declarations = Array.from(
      { length: MAX_BROWSER_LIVE_GUI_COMPONENTS },
      (_, index) => component("component-" + index, "root", index),
    );
    const previousError = console.error;
    console.error = () => undefined;
    try {
      gui.actions.addGuiBatch(declarations);
      gui.actions.addGui(
        component("over-the-owner-limit", "root", declarations.length),
      );
    } finally {
      console.error = previousError;
    }

    expect(gui.configStore.size()).toBe(MAX_BROWSER_LIVE_GUI_COMPONENTS);
    expect(
      Object.keys(gui.store.get().guiUuidSetFromContainerUuid.root!),
    ).toHaveLength(MAX_BROWSER_LIVE_GUI_COMPONENTS);
    expect(notifications).toBe(1);

    gui.actions.resetGui();
    gui.actions.addGui(component("reconnected", "root", 0));
    expect(gui.configStore.get("reconnected")).toBeDefined();
  });

  it("preflights out-of-order container depth and rejects cycles atomically", () => {
    const gui = createGuiStateHarness();
    const exact = Array.from({ length: 64 }, (_, index) =>
      component(
        "depth-" + index,
        index === 0 ? "root" : "depth-" + (index - 1),
        index,
      ),
    );
    expect(gui.actions.preflightMessageBatch([...exact].reverse())).toBeNull();
    expect(
      gui.actions.preflightMessageBatch([
        ...exact,
        component("too-deep", "depth-63", 65),
      ]),
    ).toContain("deeper than 64");

    gui.actions.addGuiBatch([
      component("parent", "root", 0),
      component("child", "parent", 0),
    ]);
    const cycle = component("parent", "child", 0);
    expect(gui.actions.preflightMessageBatch([cycle])).toContain("cyclic");
    expect(gui.configStore.get("parent")?.container_uuid).toBe("root");
  });

  it("accepts group, tab, child, and presentation update in max-window-one frames", () => {
    const gui = createGuiStateHarness();
    const frames = [
      [tabs("tabs", "root")],
      [tab("alpha-tab", "tabs", "Alpha")],
      [text("alpha-child", "alpha-tab", "Alpha body")],
      [tabUpdate("alpha-tab", "tabs", "Renamed", "<svg />")],
    ] satisfies Message[][];

    for (const frame of frames) {
      expect(gui.actions.preflightMessageBatch(frame)).toBeNull();
      const message = frame[0];
      if (message.type === "GuiTabGroupMessage") gui.actions.addGui(message);
      else if (message.type === "GuiTabMessage")
        gui.actions.declareTab(message);
      else if (message.type === "GuiTabUpdateMessage")
        gui.actions.updateTab(message);
      else if (message.type === "GuiTextMessage") gui.actions.addGui(message);
    }

    expect(gui.configStore.get("tabs")).toMatchObject({
      props: {
        _tabs: [
          {
            container_id: "alpha-tab",
            label: "Renamed",
            icon_html: "<svg />",
          },
        ],
      },
    });
    expect(gui.store.get().guiUuidSetFromContainerUuid["alpha-tab"]).toEqual({
      "alpha-child": true,
    });
  });

  it("preflights group, flat declaration, and child sequentially in one frame", () => {
    const gui = createGuiStateHarness();
    const messages = [
      tabs("tabs", "root"),
      tab("alpha-tab", "tabs", "Alpha"),
      text("alpha-child", "alpha-tab", "Alpha body"),
    ] satisfies Message[];

    expect(gui.actions.preflightMessageBatch(messages)).toBeNull();
    gui.actions.addGui(messages[0] as GuiTabGroupMessage);
    gui.actions.declareTab(messages[1] as GuiTabMessage);
    gui.actions.addGui(messages[2] as GuiTextMessage);

    expect(gui.configStore.get("alpha-child")).toBeDefined();
  });

  it("rejects a dependency supplied only after its create batch must flush", () => {
    const gui = createGuiStateHarness();
    const invalidPrefix = [
      tabs("tabs", "root"),
      text("child", "late-tab", "body"),
      tab("late-tab", "tabs", "Too late"),
    ] satisfies Message[];

    expect(gui.actions.preflightMessageBatch(invalidPrefix)).toContain(
      "dispatch-batch prefix",
    );
    expect(gui.configStore.size()).toBe(0);
    expect(gui.store.get().guiUuidSetFromContainerUuid).toEqual({ root: {} });
  });

  it("keeps duplicate same-owner declarations idempotent after a metadata update", () => {
    const gui = createGuiStateHarness();
    gui.actions.addGui(tabs("tabs", "root"));
    gui.actions.declareTab(tab("alpha", "tabs", "Initial"));
    gui.actions.updateTab(tabUpdate("alpha", "tabs", "Current", "<svg />"));

    const duplicate = tab("alpha", "tabs", "Stale", null);
    expect(gui.actions.preflightMessageBatch([duplicate])).toBeNull();
    gui.actions.declareTab(duplicate);

    expect(
      (gui.configStore.get("tabs") as GuiTabGroupMessage).props._tabs,
    ).toEqual([
      {
        container_id: "alpha",
        label: "Current",
        icon_html: "<svg />",
      },
    ]);
  });

  it("rejects update-before-create and cross-owner declarations", () => {
    const gui = createGuiStateHarness();
    gui.actions.addGuiBatch([
      tabs("first-group", "root"),
      tabs("second-group", "root"),
    ]);

    expect(
      gui.actions.preflightMessageBatch([
        tabUpdate("missing", "first-group", "Missing"),
      ]),
    ).toContain("precedes");
    gui.actions.declareTab(tab("owned", "first-group", "Owned"));
    expect(
      gui.actions.preflightMessageBatch([
        tab("owned", "second-group", "Stolen"),
      ]),
    ).toContain("another group");
  });

  it("rejects tab, component, modal, and root owner collisions", () => {
    const gui = createGuiStateHarness();
    gui.actions.addGuiBatch([
      tabs("tabs", "root"),
      component("component", "root", 1),
    ]);
    gui.actions.addModal(modal("modal", 0));
    gui.actions.declareTab(tab("owned-tab", "tabs"));

    for (const uuid of ["component", "modal", "root"]) {
      expect(gui.actions.preflightMessageBatch([tab(uuid, "tabs")])).toContain(
        "collides",
      );
    }
    expect(
      gui.actions.preflightMessageBatch([component("owned-tab", "root", 2)]),
    ).toContain("collides");
    expect(
      gui.actions.preflightMessageBatch([
        { ...modal("owned-tab", 1), title: "Collision" },
      ]),
    ).toContain("owner");
  });

  it("removes a tab, nested tab descriptors, containers, and GUI subtree together", () => {
    const gui = createGuiStateHarness();
    gui.actions.addGui(tabs("outer-group", "root"));
    gui.actions.declareTab(tab("outer-tab", "outer-group", "Outer"));
    gui.actions.addGui(tabs("inner-group", "outer-tab"));
    gui.actions.declareTab(tab("inner-tab", "inner-group", "Inner"));
    gui.actions.addGui(component("leaf", "inner-tab", 0));

    const removal = {
      type: "GuiRemoveMessage",
      uuid: "outer-tab",
      removed_uuids: ["leaf", "inner-group"],
      removed_tab_uuids: ["inner-tab"],
    } satisfies Message;
    expect(gui.actions.preflightMessageBatch([removal])).toBeNull();
    gui.actions.removeGui(
      removal.uuid,
      removal.removed_uuids,
      removal.removed_tab_uuids,
    );

    expect(
      (gui.configStore.get("outer-group") as GuiTabGroupMessage).props._tabs,
    ).toEqual([]);
    expect(gui.configStore.get("inner-group")).toBeUndefined();
    expect(gui.configStore.get("leaf")).toBeUndefined();
    expect(
      gui.store.get().guiUuidSetFromContainerUuid["outer-tab"],
    ).toBeUndefined();
    expect(
      gui.store.get().guiUuidSetFromContainerUuid["inner-tab"],
    ).toBeUndefined();
    expect(
      gui.actions.preflightMessageBatch([
        tabUpdate("inner-tab", "inner-group", "Gone"),
      ]),
    ).toContain("missing tab group");
  });

  it("uses modal tab tombstones to remove locally orphaned tab subtrees", () => {
    const gui = createGuiStateHarness();
    gui.actions.addModal(modal("modal", 0));
    gui.actions.addGui(tabs("tabs", "modal"));
    gui.actions.declareTab(tab("modal-tab", "tabs"));
    gui.actions.addGui(component("leaf", "modal-tab", 0));

    const close = {
      type: "GuiCloseModalMessage",
      uuid: "modal",
      removed_uuids: ["leaf", "tabs"],
      removed_tab_uuids: ["modal-tab"],
    } satisfies Message;
    expect(gui.actions.preflightMessageBatch([close])).toBeNull();
    gui.actions.removeModal(
      close.uuid,
      close.removed_uuids,
      close.removed_tab_uuids,
    );

    expect(gui.store.get().modals).toEqual([]);
    expect(gui.configStore.size()).toBe(0);
    expect(gui.store.get().guiUuidSetFromContainerUuid).toEqual({ root: {} });
  });

  it("bounds tab tombstones separately and requires disjoint namespaces", () => {
    const gui = createGuiStateHarness();
    const removal = (removedTabUuids: string[]): Message => ({
      type: "GuiRemoveMessage",
      uuid: "missing",
      removed_uuids: [],
      removed_tab_uuids: removedTabUuids,
    });
    expect(
      gui.actions.preflightMessageBatch([
        removal(Array.from({ length: 16_384 }, (_, index) => "tab-" + index)),
      ]),
    ).toBeNull();
    expect(
      gui.actions.preflightMessageBatch([
        removal(Array.from({ length: 16_385 }, (_, index) => "tab-" + index)),
      ]),
    ).toContain("tombstones");

    expect(
      gui.actions.preflightMessageBatch([
        {
          type: "GuiRemoveMessage",
          uuid: "parent",
          removed_uuids: ["overlap"],
          removed_tab_uuids: ["overlap"],
        },
      ]),
    ).toContain("tombstones");
  });

  it("rejects removal tombstones and primaries from the wrong owner namespace", () => {
    const gui = createGuiStateHarness();
    gui.actions.addGuiBatch([
      tabs("tabs", "root"),
      component("component", "root", 1),
    ]);
    gui.actions.declareTab(tab("owned-tab", "tabs"));
    gui.actions.addModal(modal("modal", 0));

    for (const uuid of ["root", "modal", "owned-tab"]) {
      expect(
        gui.actions.preflightMessageBatch([
          {
            type: "GuiRemoveMessage",
            uuid: "missing",
            removed_uuids: [uuid],
            removed_tab_uuids: [],
          },
        ]),
      ).toContain("namespaces");
    }
    for (const uuid of ["root", "modal", "component"]) {
      expect(
        gui.actions.preflightMessageBatch([
          {
            type: "GuiRemoveMessage",
            uuid: "missing",
            removed_uuids: [],
            removed_tab_uuids: [uuid],
          },
        ]),
      ).toContain("namespaces");
    }
    for (const uuid of ["root", "modal"]) {
      expect(
        gui.actions.preflightMessageBatch([
          {
            type: "GuiRemoveMessage",
            uuid,
            removed_uuids: [],
            removed_tab_uuids: [],
          },
        ]),
      ).toContain("namespaces");
    }
    for (const uuid of ["root", "component", "owned-tab"]) {
      expect(
        gui.actions.preflightMessageBatch([
          {
            type: "GuiCloseModalMessage",
            uuid,
            removed_uuids: [],
            removed_tab_uuids: [],
          },
        ]),
      ).toContain("namespaces");
    }

    const removePrimaryTab = {
      type: "GuiRemoveMessage",
      uuid: "owned-tab",
      removed_uuids: [],
      removed_tab_uuids: [],
    } satisfies Message;
    expect(gui.actions.preflightMessageBatch([removePrimaryTab])).toBeNull();
    gui.actions.removeGui("owned-tab");
    expect(
      (gui.configStore.get("tabs") as GuiTabGroupMessage).props._tabs,
    ).toEqual([]);

    expect(
      gui.actions.preflightMessageBatch([
        {
          type: "GuiRemoveMessage",
          uuid: "missing",
          removed_uuids: [],
          removed_tab_uuids: [],
        },
        {
          type: "GuiCloseModalMessage",
          uuid: "missing-modal",
          removed_uuids: [],
          removed_tab_uuids: [],
        },
      ]),
    ).toBeNull();
  });

  it("rejects forged group snapshots and generic descriptor updates", () => {
    const gui = createGuiStateHarness();
    const forged = tabs("tabs", "root");
    forged.props._tabs = [
      { container_id: "forged", label: "Forged", icon_html: null },
    ];
    expect(gui.actions.preflightMessageBatch([forged])).toContain("snapshot");

    expect(
      gui.actions.preflightMessageBatch([
        {
          type: "GuiUpdateMessage",
          uuid: "missing",
          updates: { _tabs: [] },
        },
      ]),
    ).toContain("tab lifecycle messages");

    gui.actions.addGui(tabs("tabs", "root"));
    gui.actions.declareTab(tab("declared", "tabs"));
    expect(
      gui.actions.preflightMessageBatch([
        {
          type: "GuiUpdateMessage",
          uuid: "declared",
          updates: { label: "Forged" },
        },
      ]),
    ).toContain("tab lifecycle messages");
    expect(
      gui.actions.preflightMessageBatch([
        {
          type: "GuiUpdateMessage",
          uuid: "tabs",
          updates: {
            _tabs: [
              {
                container_id: "forged",
                label: "Forged",
                icon_html: null,
              },
            ],
          },
        },
      ]),
    ).toContain("lifecycle messages");
  });

  it("rejects an orphan child and counts explicit tabs in container depth", () => {
    const gui = createGuiStateHarness();
    gui.actions.addGui(tabs("tabs", "root"));
    expect(
      gui.actions.preflightMessageBatch([
        text("orphan", "missing-tab", "body"),
      ]),
    ).toContain("container graph");

    const nested: Message[] = [];
    let parent = "root";
    for (let index = 0; index < 31; index += 1) {
      const groupUuid = "group-" + index;
      const tabUuid = "tab-" + index;
      nested.push(tabs(groupUuid, parent));
      nested.push(tab(tabUuid, groupUuid));
      parent = tabUuid;
    }
    nested.push(component("node-at-depth-63", parent, 0));
    nested.push(component("node-at-depth-64", "node-at-depth-63", 0));
    expect(gui.actions.preflightMessageBatch(nested)).toBeNull();

    expect(
      gui.actions.preflightMessageBatch([
        ...nested,
        component("leaf-at-depth-65", "node-at-depth-64", 0),
      ]),
    ).toContain("deeper than 64");
    expect(
      gui.actions.preflightMessageBatch([
        ...nested,
        tabs("tabs-at-depth-65", "node-at-depth-64"),
      ]),
    ).toContain("deeper than 64");
  });

  it("treats a modal shell as depth zero at the exact graph boundary", () => {
    const gui = createGuiStateHarness();
    const modalRoot = modal("modal-root", 0);
    const exact: Message[] = [modalRoot];
    for (let depth = 1; depth <= 64; depth += 1) {
      exact.push(
        component(
          "modal-depth-" + depth,
          depth === 1 ? modalRoot.uuid : "modal-depth-" + (depth - 1),
          depth,
        ),
      );
    }

    expect(gui.actions.preflightMessageBatch(exact)).toBeNull();
    expect(
      gui.actions.preflightMessageBatch([
        ...exact,
        component("modal-leaf-depth-65", "modal-depth-64", 65),
      ]),
    ).toContain("deeper than 64");
    expect(
      gui.actions.preflightMessageBatch([
        ...exact,
        tabs("modal-tabs-depth-65", "modal-depth-64"),
      ]),
    ).toContain("deeper than 64");
  });

  it("keeps a rejected frame entirely side-effect free", () => {
    const gui = createGuiStateHarness();
    gui.actions.addGui(tabs("tabs", "root"));
    const beforeGroup = gui.configStore.get("tabs");
    const frame = [
      tab("valid-tab", "tabs", "Valid"),
      text("child", "valid-tab", "body"),
      tabUpdate("missing-tab", "tabs", "Invalid"),
    ] satisfies Message[];

    expect(gui.actions.preflightMessageBatch(frame)).toContain("precedes");
    expect(gui.configStore.get("tabs")).toBe(beforeGroup);
    expect(gui.configStore.get("child")).toBeUndefined();
    expect(gui.store.get().guiUuidSetFromContainerUuid).toEqual({
      root: { tabs: true },
    });
  });

  it("rejects non-container parents", () => {
    const gui = createGuiStateHarness();
    expect(
      gui.actions.preflightMessageBatch([
        checkbox("input", "root"),
        component("child", "input", 0),
      ]),
    ).toContain("container graph");
  });

  it("rejects a whole declaration batch instead of retaining valid siblings", () => {
    const gui = createGuiStateHarness();
    const invalid = component("invalid", "root", 1);
    invalid.props.label = "x".repeat(MAX_GUI_COMMON_STRING_CODE_UNITS + 1);
    const previousError = console.error;
    console.error = () => undefined;
    try {
      gui.actions.addGuiBatch([component("valid", "root", 0), invalid]);
    } finally {
      console.error = previousError;
    }
    expect(gui.configStore.size()).toBe(0);
    expect(gui.store.get().guiUuidSetFromContainerUuid).toEqual({ root: {} });
  });

  it("rejects oversized common renderer strings on create and update", () => {
    const gui = createGuiStateHarness();
    const valid = component("field", "root", 0);
    valid.props.label = "x".repeat(MAX_GUI_COMMON_STRING_CODE_UNITS);
    gui.actions.addGui(valid);
    gui.actions.updateGuiProps("field", {
      label: "x".repeat(MAX_GUI_COMMON_STRING_CODE_UNITS + 1),
    });
    gui.actions.addModal({
      ...modal("oversized-modal", 0),
      title: "x".repeat(MAX_GUI_COMMON_STRING_CODE_UNITS + 1),
    });

    expect(gui.configStore.get("field")).toBe(valid);
    expect(gui.store.get().modals).toEqual([]);
  });

  it("includes commands in the shared page text ledger and releases reset", () => {
    const gui = createGuiStateHarness();
    const halfCommand = "x".repeat(MAX_GUI_COMMON_STRING_CODE_UNITS);
    const exactCount =
      MAX_BROWSER_GUI_TEXT_CODE_UNITS / (MAX_GUI_COMMON_STRING_CODE_UNITS * 2);
    const exact = Array.from({ length: exactCount }, (_, index) =>
      command("command-" + index, halfCommand, halfCommand),
    );
    expect(gui.actions.preflightMessageBatch(exact)).toBeNull();
    gui.actions.addCommandBatch(exact);
    expect(Object.keys(gui.store.get().commands)).toHaveLength(exactCount);

    expect(
      gui.actions.preflightMessageBatch([
        command("aggregate-overflow", "x", null),
      ]),
    ).toContain("aggregate UI text budget");

    gui.actions.resetGui();
    gui.actions.addCommand(command("after-reset", halfCommand, halfCommand));
    expect(gui.store.get().commands["after-reset"]).toBeDefined();
  });

  it("detaches retained image bytes from a much larger websocket frame", () => {
    const gui = createGuiStateHarness();
    const frame = new ArrayBuffer(1024 * 1024);
    const oneByte = new Uint8Array(frame, 512, 1) as Uint8Array<ArrayBuffer>;
    const image: GuiImageMessage = {
      type: "GuiImageMessage",
      uuid: "image",
      container_uuid: "root",
      props: {
        order: 0,
        label: null,
        _data: oneByte,
        _format: "png",
        visible: true,
      },
    };

    gui.actions.addGui(image);

    const retained = gui.configStore.get("image") as GuiImageMessage;
    expect(retained.props._data).not.toBe(oneByte);
    expect(retained.props._data.byteLength).toBe(1);
    expect(retained.props._data.buffer.byteLength).toBe(1);
  });

  it("keeps upload progress scoped to the transfer that owns the control", () => {
    const gui = createGuiStateHarness();
    gui.actions.updateUploadState({
      componentId: "upload",
      transferUuid: "old",
      uploadedBytes: 0,
      totalBytes: 10,
      filename: "old.bin",
    });
    gui.actions.updateUploadState({
      componentId: "upload",
      transferUuid: "old",
      uploadedBytes: 5,
      totalBytes: 10,
    });
    expect(gui.store.get().uploadsInProgress.upload).toMatchObject({
      transferUuid: "old",
      uploadedBytes: 5,
    });

    // A new selection supersedes the active display immediately.
    gui.actions.updateUploadState({
      componentId: "upload",
      transferUuid: "new",
      uploadedBytes: 0,
      totalBytes: 20,
      filename: "new.bin",
    });
    // Late completion/ACK work from the old async call cannot overwrite or
    // clear the new selection.
    gui.actions.updateUploadState({
      componentId: "upload",
      transferUuid: "old",
      uploadedBytes: 10,
      totalBytes: 10,
    });
    gui.actions.clearUploadState("upload", "old");
    expect(gui.store.get().uploadsInProgress.upload).toEqual({
      transferUuid: "new",
      uploadedBytes: 0,
      totalBytes: 20,
      filename: "new.bin",
    });

    gui.actions.clearUploadState("upload", "new");
    expect(gui.store.get().uploadsInProgress.upload).toBeUndefined();

    // An ACK by itself cannot recreate state after completion/reset.
    gui.actions.updateUploadState({
      componentId: "upload",
      transferUuid: "new",
      uploadedBytes: 20,
      totalBytes: 20,
    });
    expect(gui.store.get().uploadsInProgress.upload).toBeUndefined();
  });
});

describe("applyGuiConfigUpdate", () => {
  it("ignores inherited/prototype-setter names and defines only real props", () => {
    const config = component("field", "root", 1);
    const updates = JSON.parse(
      '{"__proto__":{"polluted":true},"toString":"bad","label":"updated"}',
    ) as Record<string, unknown>;
    const errors: unknown[] = [];
    const previousError = console.error;
    console.error = (...args) => errors.push(args);
    try {
      const updated = applyGuiConfigUpdate(config, updates) as GuiFolderMessage;
      expect(updated.props.label).toBe("updated");
      expect(Object.getPrototypeOf(updated.props)).toBe(Object.prototype);
      expect(Object.hasOwn(updated.props, "__proto__")).toBe(false);
      expect(Object.hasOwn(updated.props, "toString")).toBe(false);
      expect(errors).toHaveLength(2);
    } finally {
      console.error = previousError;
    }
  });
});
