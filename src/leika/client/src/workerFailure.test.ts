import { describe, expect, it, vi } from "vitest";

import {
  FatalWorkerEvent,
  WorkerEventGate,
  WorkerFailureController,
} from "./workerFailure";

describe("WorkerEventGate", () => {
  it("permanently rejects callbacks queued after it closes", () => {
    const gate = new WorkerEventGate();
    expect(gate.acceptsEvents).toBe(true);
    expect(gate.close()).toBe(true);
    expect(gate.acceptsEvents).toBe(false);
    expect(gate.close()).toBe(false);
  });
});

describe("WorkerFailureController", () => {
  it("latches before cleanup and announces exactly one fatal transition", () => {
    const events: FatalWorkerEvent[] = [];
    const reference: { current: WorkerFailureController | null } = {
      current: null,
    };
    const shutdown = vi.fn(() => {
      expect(reference.current?.hasFailed).toBe(true);
    });
    const controller = new WorkerFailureController(
      shutdown,
      (event) => events.push(event),
      () => undefined,
    );
    reference.current = controller;

    controller.fail("Decoder failed", new Error("bad frame"));
    controller.fail("A stale callback failed too");

    expect(shutdown).toHaveBeenCalledOnce();
    expect(events).toEqual([
      { type: "fatal", reason: "Decoder failed: bad frame" },
    ]);
  });

  it("turns an outgoing post failure into the same fatal transition", () => {
    const events: FatalWorkerEvent[] = [];
    const controller = new WorkerFailureController(
      () => undefined,
      (event) => events.push(event),
      () => undefined,
    );

    expect(
      controller.post("Could not post a batch", () => {
        throw new DOMException("buffer is detached", "DataCloneError");
      }),
    ).toBe(false);
    expect(controller.hasFailed).toBe(true);
    expect(events[0]?.reason).toContain("buffer is detached");

    const stalePost = vi.fn();
    expect(controller.post("stale", stalePost)).toBe(false);
    expect(stalePost).not.toHaveBeenCalled();
  });

  it("surfaces an error when the fatal event itself cannot be posted", () => {
    const surfaced: unknown[] = [];
    const postError = new Error("worker channel is gone");
    const controller = new WorkerFailureController(
      () => undefined,
      () => {
        throw postError;
      },
      (error) => surfaced.push(error),
    );

    controller.fail("Decoder failed");

    expect(surfaced).toEqual([postError]);
  });

  it("still announces a fatal event when cleanup throws", () => {
    const events: FatalWorkerEvent[] = [];
    const controller = new WorkerFailureController(
      () => {
        throw new Error("socket close failed");
      },
      (event) => events.push(event),
      () => undefined,
    );

    controller.fail("Decode failed");

    expect(events[0]?.reason).toContain("cleanup also failed");
  });
});
