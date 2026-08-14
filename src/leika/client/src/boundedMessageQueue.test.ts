import { describe, expect, it } from "vitest";

import {
  BoundedMessageQueue,
  MAX_QUEUED_MESSAGE_FRAME_BYTES,
  MAX_QUEUED_MESSAGE_METADATA_BYTES,
  MAX_QUEUED_MESSAGES,
} from "./boundedMessageQueue";
import type { Message } from "./WebsocketMessages";

const message = (index: number) =>
  ({ type: "ServerPongMessage", sent_ms: index }) as Message;

describe("BoundedMessageQueue", () => {
  it("admits exact byte and message boundaries, then drains accounting", () => {
    const queue = new BoundedMessageQueue();
    const messages = Array.from({ length: MAX_QUEUED_MESSAGES }, (_, index) =>
      message(index),
    );
    expect(
      queue.enqueue(
        messages,
        MAX_QUEUED_MESSAGE_FRAME_BYTES,
        MAX_QUEUED_MESSAGE_METADATA_BYTES,
      ),
    ).toBe(true);
    expect(queue.messageCount).toBe(MAX_QUEUED_MESSAGES);
    expect(queue.frameBytes).toBe(MAX_QUEUED_MESSAGE_FRAME_BYTES);
    expect(queue.metadataBytes).toBe(MAX_QUEUED_MESSAGE_METADATA_BYTES);
    expect(queue.enqueue([message(99)], 0, 0)).toBe(false);

    expect(queue.drain()).toEqual(messages);
    expect(queue.messageCount).toBe(0);
    expect(queue.frameBytes).toBe(0);
    expect(queue.metadataBytes).toBe(0);
  });

  it("rejects a burst before enqueueing the batch that exceeds bytes", () => {
    const queue = new BoundedMessageQueue();
    expect(
      queue.enqueue([message(1)], MAX_QUEUED_MESSAGE_FRAME_BYTES - 1, 1),
    ).toBe(true);
    expect(queue.enqueue([message(2)], 2, 1)).toBe(false);
    expect(queue.messageCount).toBe(1);
    expect(queue.frameBytes).toBe(MAX_QUEUED_MESSAGE_FRAME_BYTES - 1);
  });

  it("independently bounds decompressed message-tree metadata", () => {
    const queue = new BoundedMessageQueue();
    expect(
      queue.enqueue([message(1)], 16, MAX_QUEUED_MESSAGE_METADATA_BYTES - 1),
    ).toBe(true);
    expect(queue.enqueue([message(2)], 16, 2)).toBe(false);
    expect(queue.metadataBytes).toBe(MAX_QUEUED_MESSAGE_METADATA_BYTES - 1);
  });

  it("reset releases all old-connection batches and validates frame sizes", () => {
    const queue = new BoundedMessageQueue();
    queue.enqueue([message(1), message(2)], 20, 40);
    queue.reset();
    expect(queue.drain()).toEqual([]);
    expect(queue.enqueue([message(3)], Number.NaN, 1)).toBe(false);
    expect(
      queue.enqueue([message(3)], MAX_QUEUED_MESSAGE_FRAME_BYTES + 1, 1),
    ).toBe(false);
  });

  it("does not retain an empty worker batch", () => {
    const queue = new BoundedMessageQueue();
    expect(
      queue.enqueue(
        [],
        MAX_QUEUED_MESSAGE_FRAME_BYTES,
        MAX_QUEUED_MESSAGE_METADATA_BYTES,
      ),
    ).toBe(true);
    expect(queue.frameBytes).toBe(0);
    expect(queue.messageCount).toBe(0);
    expect(queue.metadataBytes).toBe(0);
  });

  it("drains accounting while preserving original wire-frame boundaries", () => {
    const queue = new BoundedMessageQueue();
    const first = [message(1), message(2)];
    const second = [message(3)];
    queue.enqueue(first, 10, 20);
    queue.enqueue(second, 30, 40);

    expect(queue.drainBatches()).toEqual([first, second]);
    expect(queue.messageCount).toBe(0);
    expect(queue.frameBytes).toBe(0);
    expect(queue.metadataBytes).toBe(0);
  });
});
