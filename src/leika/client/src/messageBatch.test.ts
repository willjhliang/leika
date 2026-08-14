import { describe, expect, it, vi } from "vitest";

import type { Message } from "./WebsocketMessages";
import {
  dispatchMessageBatch,
  processPreflightedMessageBatches,
} from "./messageBatch";

describe("dispatchMessageBatch", () => {
  it("batches contiguous declarations without changing lifecycle order", () => {
    const first = {
      type: "GuiFolderMessage",
      uuid: "first",
      container_uuid: "root",
      props: {
        order: 0,
        label: "First",
        visible: true,
        expand_by_default: false,
      },
    } satisfies Message;
    const second = { ...first, uuid: "second" } satisfies Message;
    const third = { ...first, uuid: "third" } satisfies Message;
    const modal = {
      type: "GuiModalMessage",
      uuid: "modal",
      order: 0,
      title: "Modal",
    } satisfies Message;
    const update = {
      type: "GuiUpdateMessage",
      uuid: "first",
      updates: { visible: false },
    } satisfies Message;
    const events: string[] = [];

    const updates = dispatchMessageBatch(
      [first, second, modal, third, update],
      (message) => {
        events.push("message:" + message.type);
        if (message === update) return update;
        return undefined;
      },
      undefined,
      {
        guiComponents: (messages) =>
          events.push("gui:" + messages.map(({ uuid }) => uuid).join(",")),
        modals: (messages) =>
          events.push("modal:" + messages.map(({ uuid }) => uuid).join(",")),
        commands: () => events.push("commands"),
      },
    );

    expect(events).toEqual([
      "gui:first,second",
      "modal:modal",
      "gui:third",
      "message:GuiUpdateMessage",
    ]);
    expect(updates.get("first")).toEqual({ visible: false });
  });

  it("flushes group, tab lifecycle, and child batches in dependency order", () => {
    const group = {
      type: "GuiTabGroupMessage",
      uuid: "group",
      container_uuid: "root",
      props: { _tabs: [], order: 0, visible: true },
    } satisfies Message;
    const declaration = {
      type: "GuiTabMessage",
      uuid: "tab",
      group_uuid: "group",
      label: "Tab",
      icon_html: null,
    } satisfies Message;
    const update = {
      ...declaration,
      type: "GuiTabUpdateMessage",
      label: "Renamed",
    } satisfies Message;
    const child = {
      type: "GuiFolderMessage",
      uuid: "child",
      container_uuid: "tab",
      props: {
        order: 0,
        label: "Child",
        visible: true,
        expand_by_default: false,
      },
    } satisfies Message;
    const remove = {
      type: "GuiRemoveMessage",
      uuid: "tab",
      removed_uuids: ["child"],
      removed_tab_uuids: [],
    } satisfies Message;
    const events: string[] = [];

    dispatchMessageBatch(
      [group, declaration, update, child, remove],
      (message) => {
        events.push("message:" + message.type);
        return undefined;
      },
      undefined,
      {
        guiComponents: (messages) =>
          events.push("gui:" + messages.map(({ uuid }) => uuid).join(",")),
        modals: () => undefined,
        commands: () => undefined,
        tabs: (messages) =>
          events.push(
            "tabs:" +
              messages.map(({ type, uuid }) => type + ":" + uuid).join(","),
          ),
      },
    );

    expect(events).toEqual([
      "gui:group",
      "tabs:GuiTabMessage:tab,GuiTabUpdateMessage:tab",
      "gui:child",
      "message:GuiRemoveMessage",
    ]);
  });

  it("reports one broken message and continues with the rest of the batch", () => {
    const broken = {
      type: "RunJavascriptMessage",
      source: "throw new Error('broken')",
    } satisfies Message;
    const update = {
      type: "GuiUpdateMessage",
      uuid: "field",
      updates: { value: 2 },
    } satisfies Message;
    const reportError = vi.fn();
    const handleMessage = vi.fn((message: Message) => {
      if (message === broken) throw new Error("broken");
      if (message === update)
        return { uuid: update.uuid, updates: update.updates };
      return undefined;
    });

    const updates = dispatchMessageBatch(
      [broken, update],
      handleMessage,
      reportError,
    );

    expect(reportError).toHaveBeenCalledOnce();
    expect(reportError).toHaveBeenCalledWith(broken, expect.any(Error));
    expect(handleMessage).toHaveBeenCalledTimes(2);
    expect(updates.get("field")).toEqual({ value: 2 });
  });

  it("retains prior updates when a remove handler itself fails", () => {
    const before = {
      type: "GuiUpdateMessage",
      uuid: "field",
      updates: { value: 1 },
    } satisfies Message;
    const remove = {
      type: "GuiRemoveMessage",
      uuid: "field",
      removed_uuids: [],
      removed_tab_uuids: [],
    } satisfies Message;
    const after = {
      type: "GuiUpdateMessage",
      uuid: "field",
      updates: { disabled: true },
    } satisfies Message;

    const updates = dispatchMessageBatch(
      [before, remove, after],
      (message) => {
        if (message === remove) throw new Error("remove side effect failed");
        if (message.type === "GuiUpdateMessage") {
          return { uuid: message.uuid, updates: message.updates };
        }
        return undefined;
      },
      vi.fn(),
    );

    expect(updates.get("field")).toEqual({ value: 1, disabled: true });
  });

  it("commits updates at lifecycle boundaries with chronological last-writer semantics", () => {
    const declaration = (uuid: string, visible: boolean): Message => ({
      type: "GuiFolderMessage",
      uuid,
      container_uuid: "root",
      props: {
        order: 0,
        label: uuid,
        visible,
        expand_by_default: false,
      },
    });
    const update = (uuid: string, visible: boolean): Message => ({
      type: "GuiUpdateMessage",
      uuid,
      updates: { visible },
    });
    const values = new Map<string, boolean>();
    const apply = (messages: readonly Message[]) => {
      dispatchMessageBatch(
        messages,
        (message) => {
          if (message.type === "GuiUpdateMessage") {
            return { uuid: message.uuid, updates: message.updates };
          }
          if (message.type === "GuiRemoveMessage") {
            values.delete(message.uuid);
            const removed = (message as Message & { removed_uuids?: string[] })
              .removed_uuids;
            for (const uuid of removed ?? []) values.delete(uuid);
          }
          return undefined;
        },
        undefined,
        {
          guiComponents: (components) => {
            for (const component of components) {
              values.set(component.uuid, component.props.visible);
            }
          },
          modals: () => undefined,
          commands: () => undefined,
          guiUpdates: (updates) => {
            for (const [uuid, props] of updates) {
              if (values.has(uuid) && typeof props.visible === "boolean") {
                values.set(uuid, props.visible);
              }
            }
          },
        },
      );
    };

    apply([
      declaration("same", true),
      update("same", false),
      declaration("same", true),
    ]);
    expect(values.get("same")).toBe(true);

    values.clear();
    apply([update("absent", false), declaration("absent", true)]);
    expect(values.get("absent")).toBe(true);

    values.set("child", true);
    apply([
      update("child", false),
      {
        type: "GuiRemoveMessage",
        uuid: "parent",
        removed_uuids: ["child"],
        removed_tab_uuids: [],
      },
      declaration("child", true),
    ]);
    expect(values.get("child")).toBe(true);
  });
});

describe("processPreflightedMessageBatches", () => {
  it("applies no side effects from a frame whose later message is invalid", () => {
    const first = {
      type: "SetGuiPanelLabelMessage",
      label: "must not apply",
    } satisfies Message;
    const invalid = {
      type: "SetGuiPanelLabelMessage",
      label: "oversized",
    } satisfies Message;
    const apply = vi.fn();
    const fail = vi.fn();

    expect(
      processPreflightedMessageBatches(
        [[first, invalid]],
        (messages) => (messages.includes(invalid) ? "frame rejected" : null),
        (messages) => {
          apply(messages);
          return null;
        },
        fail,
      ),
    ).toBe(false);
    expect(apply).not.toHaveBeenCalled();
    expect(fail).toHaveBeenCalledWith("frame rejected");
  });

  it("keeps prior valid frames but stops before a rejected next frame", () => {
    const valid = [
      { type: "ServerPongMessage", sent_ms: 1 },
    ] satisfies Message[];
    const invalid = [
      { type: "SetGuiPanelLabelMessage", label: "bad" },
    ] satisfies Message[];
    const applied: Message[][] = [];

    processPreflightedMessageBatches(
      [valid, invalid],
      (messages) => (messages === invalid ? "bad frame" : null),
      (messages) => {
        applied.push([...messages]);
        return null;
      },
      vi.fn(),
    );

    expect(applied).toEqual([valid]);
  });

  it("fails the connection when bootstrap preparation cannot apply", () => {
    const fail = vi.fn();
    const applied = processPreflightedMessageBatches(
      [[{ type: "ServerPongMessage", sent_ms: 1 }]],
      () => null,
      () => "bootstrap failed",
      fail,
    );
    expect(applied).toBe(false);
    expect(fail).toHaveBeenCalledWith("bootstrap failed");
  });
});
