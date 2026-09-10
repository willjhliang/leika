import { describe, expect, it } from "vitest";
import { BoundedMessageQueue } from "./boundedMessageQueue";
import { processMessageQueueSlice } from "./messageQueueProcessor";
import { makeMessageQueueScheduler } from "./messageQueueScheduler";

function queuedFrames() {
  const queue = new BoundedMessageQueue();
  for (let index = 0; index < 3; index += 1) {
    queue.enqueue(
      [
        { type: "ServerPongMessage", sent_ms: index },
        { type: "ServerPongMessage", sent_ms: index },
      ],
      10,
      20,
    );
  }
  return queue;
}

describe("message queue time slicing", () => {
  it("yields complete frames and schedules pending work until idle", () => {
    const queue = queuedFrames();
    let time = 0;
    const frames = new Map<number, () => void>();
    let nextHandle = 0;
    const applied: number[] = [];
    const scheduler = makeMessageQueueScheduler(
      () =>
        processMessageQueueSlice(
          queue,
          (batch) => {
            expect(batch).toHaveLength(2);
            const message = batch[0];
            if (message.type !== "ServerPongMessage")
              throw new Error("Expected pong");
            applied.push(message.sent_ms);
            time += 9;
            return true;
          },
          () => time,
        ),
      {
        isHidden: () => false,
        requestFrame: (callback) => {
          frames.set(++nextHandle, callback);
          return nextHandle;
        },
        cancelFrame: (handle) => {
          frames.delete(handle);
        },
        setTimer: () => {
          throw new Error("Unexpected hidden timer");
        },
        clearTimer: () => undefined,
      },
    );
    const tick = () => {
      expect(frames.size).toBe(1);
      const [handle, callback] = [...frames][0];
      frames.delete(handle);
      callback();
    };
    scheduler.schedule();
    tick();
    expect(applied).toEqual([0]);
    expect(queue.frameBytes).toBe(20);
    expect(queue.metadataBytes).toBe(40);
    tick();
    expect(applied).toEqual([0, 1]);
    tick();
    expect(applied).toEqual([0, 1, 2]);
    expect(queue.messageCount).toBe(0);
    expect(frames.size).toBe(0);
  });

  it("finishes cheap batches in one slice", () => {
    const queue = queuedFrames();
    let count = 0;
    expect(
      processMessageQueueSlice(
        queue,
        () => {
          count += 1;
          return true;
        },
        () => 0,
      ),
    ).toBe(false);
    expect(count).toBe(3);
    expect(queue.messageCount).toBe(0);
  });

  it("does not dispatch or reschedule later frames after rejection", () => {
    const queue = queuedFrames();
    let count = 0;
    expect(
      processMessageQueueSlice(queue, () => {
        count += 1;
        return false;
      }),
    ).toBe(false);
    expect(count).toBe(1);
    expect(queue.messageCount).toBe(4);
    queue.reset();
    expect(
      processMessageQueueSlice(queue, () => {
        throw new Error("stale frame");
      }),
    ).toBe(false);
  });
});
