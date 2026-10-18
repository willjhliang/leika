import { describe, expect, it } from "vitest";

import {
  GuiCheckboxMessage,
  GuiFolderMessage,
  GuiFormMessage,
  GuiImageMessage,
  GuiModalMessage,
  GuiProgressBarMessage,
  GuiRemoveMessage,
  RegisterCommandMessage,
  GuiTabGroupMessage,
  GuiTabMessage,
  GuiTabUpdateMessage,
} from "../WebsocketMessages";
import { applyGuiConfigUpdate, createGuiState } from "./GuiState";

function createGuiStateHarness(): ReturnType<typeof createGuiState> {
  return createGuiState();
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
      popup: false,
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
    props: { order: 0, visible: true },
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
    props: { label, _icon_html: iconHtml },
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
    props: { label, _icon_html: iconHtml },
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

function removal(uuid: string, removedUuids: string[] = []): GuiRemoveMessage {
  return { type: "GuiRemoveMessage", uuid, removed_uuids: removedUuids };
}

function tabsOf(gui: ReturnType<typeof createGuiState>, uuid: string) {
  return (gui.store.get().tabsFromGroupUuid[uuid] ?? []).map(
    (tab) => tab.props.label,
  );
}

describe("createGuiState", () => {
  it("keeps modals in protocol order and replaces a redeclared modal", () => {
    const gui = createGuiStateHarness();
    gui.actions.applyMessages([
      modal("last", 20),
      modal("first", 5),
      modal("middle", 10),
    ]);
    gui.actions.applyMessages([{ ...modal("last", 1), title: "Replacement" }]);

    expect(gui.store.get().modals.map(({ uuid }) => uuid)).toEqual([
      "last",
      "first",
      "middle",
    ]);
    expect(gui.store.get().modals[0].title).toBe("Replacement");
  });

  it("moves a redeclared component out of its previous container", () => {
    const gui = createGuiStateHarness();
    gui.actions.applyMessages([
      component("left", "root", 0),
      component("right", "root", 1),
      component("shared", "left", 1),
    ]);
    gui.actions.applyMessages([component("shared", "right", 2)]);

    const state = gui.store.get();
    expect(state.guiUuidSetFromContainerUuid.left).toBeUndefined();
    expect(state.guiUuidSetFromContainerUuid.right).toEqual({ shared: true });
    expect(state.guiOrderFromUuid.shared).toBe(2);
    expect(gui.configStore.get("shared")?.container_uuid).toBe("right");
  });

  it("applies a create followed by updates in one frame", () => {
    const gui = createGuiStateHarness();
    gui.actions.applyMessages([
      component("folder", "root", 0),
      { type: "GuiUpdateMessage", uuid: "folder", updates: { label: "A" } },
      { type: "GuiUpdateMessage", uuid: "folder", updates: { order: 7 } },
    ]);

    const folder = gui.configStore.get("folder") as GuiFolderMessage;
    expect(folder.props.label).toBe("A");
    expect(folder.props.order).toBe(7);
    expect(gui.store.get().guiOrderFromUuid.folder).toBe(7);
  });

  it("leaves tree and order snapshots alone for property updates", () => {
    const gui = createGuiStateHarness();
    gui.actions.applyMessages([component("folder", "root", 0)]);
    const before = gui.store.get();

    gui.actions.updateGuiProps("folder", { label: "renamed" });

    expect(gui.store.get()).toBe(before);
    expect(
      (gui.configStore.get("folder") as GuiFolderMessage).props.label,
    ).toBe("renamed");
  });

  it("clears the connection-owned workspace namespace on reset", () => {
    const gui = createGuiStateHarness();
    gui.store.set({ workspaceId: "previous-workspace" });

    gui.actions.resetGui();

    expect(gui.store.get().workspaceId).toBeNull();
  });

  it("treats removal of an unknown component as idempotent", () => {
    const gui = createGuiStateHarness();
    expect(() => gui.actions.applyMessages([removal("missing")])).not.toThrow();
    expect(gui.store.get().guiUuidSetFromContainerUuid).toEqual({ root: {} });
  });

  it("purges the descendants the server lists in one subtree removal", () => {
    const gui = createGuiStateHarness();
    gui.actions.applyMessages([
      component("folder", "root", 0),
      form("form", "folder"),
      tabs("tabs", "form"),
      tab("individual-tab", "tabs", "Individual"),
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

    gui.actions.applyMessages([
      removal("folder", ["form", "tabs", "individual-tab", "nested", "leaf"]),
    ]);

    for (const uuid of ["folder", "form", "tabs", "nested", "leaf"])
      expect(gui.configStore.get(uuid)).toBeUndefined();
    expect(gui.store.get().guiUuidSetFromContainerUuid).toEqual({ root: {} });
    expect(gui.store.get().guiOrderFromUuid).toEqual({});
    expect(gui.store.get().uploadsInProgress).toEqual({});
    expect(gui.store.get().tabsFromGroupUuid).toEqual({});
  });

  it("purges a modal's nested component subtree when the modal closes", () => {
    const gui = createGuiStateHarness();
    gui.actions.applyMessages([
      modal("modal", 0),
      component("folder", "modal", 0),
      component("leaf", "folder", 0),
    ]);

    gui.actions.applyMessages([
      {
        type: "GuiCloseModalMessage",
        uuid: "modal",
        removed_uuids: ["folder", "leaf"],
      },
    ]);

    expect(gui.store.get().modals).toEqual([]);
    expect(gui.configStore.get("folder")).toBeUndefined();
    expect(gui.configStore.get("leaf")).toBeUndefined();
    expect(gui.store.get().guiUuidSetFromContainerUuid).toEqual({ root: {} });
  });

  it("derives tab descriptors from the flat tab lifecycle", () => {
    const gui = createGuiStateHarness();
    gui.actions.applyMessages([
      tabs("group", "root"),
      tab("first", "group", "First"),
      tab("second", "group", "Second"),
      component("child", "second", 0),
      tabUpdate("first", "group", "Renamed"),
    ]);
    expect(tabsOf(gui, "group")).toEqual(["Renamed", "Second"]);

    // A redeclared group keeps the tabs, which have their own lifecycle.
    gui.actions.applyMessages([tabs("group", "root")]);
    expect(tabsOf(gui, "group")).toEqual(["Renamed", "Second"]);
    expect(gui.store.get().guiUuidSetFromContainerUuid.second).toEqual({
      child: true,
    });
  });

  it("removes a tab, nested tab descriptors, containers, and GUI subtree together", () => {
    const gui = createGuiStateHarness();
    gui.actions.applyMessages([
      tabs("outer-group", "root"),
      tab("outer-tab", "outer-group", "Outer"),
      tabs("inner-group", "outer-tab"),
      tab("inner-tab", "inner-group", "Inner"),
      component("leaf", "inner-tab", 0),
    ]);

    gui.actions.applyMessages([
      removal("outer-tab", ["inner-group", "inner-tab", "leaf"]),
    ]);

    expect(tabsOf(gui, "outer-group")).toEqual([]);
    expect(gui.configStore.get("inner-group")).toBeUndefined();
    expect(gui.configStore.get("leaf")).toBeUndefined();
    const containers = gui.store.get().guiUuidSetFromContainerUuid;
    expect(containers["outer-tab"]).toBeUndefined();
    expect(containers["inner-tab"]).toBeUndefined();
  });

  it("registers, updates and removes commands", () => {
    const gui = createGuiStateHarness();
    gui.actions.applyMessages([
      command("save", "Save"),
      {
        type: "CommandUpdateMessage",
        uuid: "save",
        updates: { label: "Save all" },
      },
    ]);
    expect(gui.store.get().commands.save.props.label).toBe("Save all");

    gui.actions.applyMessages([{ type: "RemoveCommandMessage", uuid: "save" }]);
    expect(gui.store.get().commands).toEqual({});
  });

  it("counts form submits so a form's popout can close on each", () => {
    const gui = createGuiStateHarness();
    gui.actions.applyMessages([
      { type: "GuiFormSubmitMessage", uuid: "form" },
      { type: "GuiFormSubmitMessage", uuid: "form" },
    ]);
    expect(gui.store.get().lastFormSubmit).toEqual({ uuid: "form", count: 2 });
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

    gui.actions.applyMessages([image]);

    const retained = gui.configStore.get("image") as GuiImageMessage;
    expect(retained.props._data).not.toBe(oneByte);
    expect(retained.props._data.byteLength).toBe(1);
    expect(retained.props._data.buffer.byteLength).toBe(1);

    gui.actions.updateGuiProps("image", { label: "renamed", visible: false });
    const renamed = gui.configStore.get("image") as GuiImageMessage;
    expect(renamed.props._data).toBe(retained.props._data);

    oneByte[0] = 99;
    gui.actions.updateGuiProps("image", { _data: oneByte });
    const replaced = gui.configStore.get("image") as GuiImageMessage;
    expect(replaced.props._data).not.toBe(oneByte);
    expect(replaced.props._data.buffer.byteLength).toBe(1);
    expect(replaced.props._data[0]).toBe(99);
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
  it("returns the same config when nothing changed", () => {
    const config = component("field", "root", 1);
    expect(applyGuiConfigUpdate(config, { label: "field", order: 1 })).toBe(
      config,
    );
    const updated = applyGuiConfigUpdate(config, { label: "updated" });
    expect((updated as GuiFolderMessage).props.label).toBe("updated");
  });

  it("keeps an input's value top-level and a display element's in its props", () => {
    const progress: GuiProgressBarMessage = {
      type: "GuiProgressBarMessage",
      uuid: "progress",
      container_uuid: "root",
      props: { order: 1, value: 10, animated: false, visible: true },
    };
    const moved = applyGuiConfigUpdate(progress, { value: 40 });
    expect((moved as GuiProgressBarMessage).props.value).toBe(40);
    expect("value" in moved).toBe(false);

    const checkbox: GuiCheckboxMessage = {
      type: "GuiCheckboxMessage",
      uuid: "checkbox",
      value: false,
      container_uuid: "root",
      props: {
        order: 1,
        label: "Check",
        hint: null,
        visible: true,
        disabled: false,
      },
    };
    const checked = applyGuiConfigUpdate(checkbox, { value: true });
    expect((checked as GuiCheckboxMessage).value).toBe(true);
    expect("value" in checked.props).toBe(false);
  });
});
