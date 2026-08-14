import { describe, expect, it, vi } from "vitest";

import { startPreviewWarmObservation } from "./previewWarmObserver";

describe("preview button warming", () => {
  it("never observes or warms a disabled preview button", () => {
    const send = vi.fn();
    const createObserver = vi.fn(() => {
      throw new Error("disabled buttons must not create an observer");
    });

    startPreviewWarmObservation(
      false,
      {} as Element,
      "preview",
      send,
      createObserver,
    )();

    expect(createObserver).not.toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
  });

  it("warms once when visible and disconnects on disable cleanup", () => {
    const send = vi.fn();
    const observe = vi.fn();
    const disconnect = vi.fn();
    let notify:
      ((entries: readonly { isIntersecting: boolean }[]) => void) | undefined;
    const cleanup = startPreviewWarmObservation(
      true,
      {} as Element,
      "preview",
      send,
      (callback) => {
        notify = callback;
        return { disconnect, observe };
      },
    );

    expect(observe).toHaveBeenCalledOnce();
    notify?.([{ isIntersecting: false }]);
    expect(send).not.toHaveBeenCalled();
    notify?.([{ isIntersecting: true }]);
    expect(disconnect).toHaveBeenCalledOnce();
    expect(send).toHaveBeenCalledWith({
      type: "GuiPreviewWarmMessage",
      uuid: "preview",
    });
    notify?.([{ isIntersecting: true }]);
    expect(send).toHaveBeenCalledOnce();

    // React invokes this effect cleanup before rerunning it with disabled=true.
    cleanup();
    expect(disconnect).toHaveBeenCalledTimes(2);
  });
});
