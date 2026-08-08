import { describe, expect, it, vi } from "vitest";

import type { Message } from "./WebsocketMessages";
import { dispatchMessageBatch } from "./messageBatch";

describe("dispatchMessageBatch", () => {
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

  it("preserves remove ordering while isolating a failing remove handler", () => {
    const before = {
      type: "GuiUpdateMessage",
      uuid: "field",
      updates: { value: 1 },
    } satisfies Message;
    const remove = {
      type: "GuiRemoveMessage",
      uuid: "field",
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

    expect(updates.get("field")).toEqual({ disabled: true });
  });
});
