import type { Message } from "./WebsocketMessages";

const MEBIBYTE = 1024 * 1024;
/** Worker buffers retained by queued typed-array messages before React drains
 * them on the next frame/timer. */
export const MAX_QUEUED_MESSAGE_FRAME_BYTES = 512 * MEBIBYTE;
/** Decompressed metadata becomes strings/objects rather than sharing the raw
 * transferred frame, so it has an independent aggregate bound. */
export const MAX_QUEUED_MESSAGE_METADATA_BYTES = 256 * MEBIBYTE;
/** Bound plain-object work even when batches contain no binary payload. */
export const MAX_QUEUED_MESSAGES = 4_096;

type QueuedBatch = {
  messages: Message[];
  frameBytes: number;
  metadataBytes: number;
};

export class BoundedMessageQueue {
  private readonly batches: QueuedBatch[] = [];
  private frameBytesValue = 0;
  private metadataBytesValue = 0;
  private messageCountValue = 0;

  get frameBytes(): number {
    return this.frameBytesValue;
  }

  get messageCount(): number {
    return this.messageCountValue;
  }

  get metadataBytes(): number {
    return this.metadataBytesValue;
  }

  enqueue(
    messages: Message[],
    frameBytes: number,
    metadataBytes: number,
  ): boolean {
    if (
      !Number.isSafeInteger(frameBytes) ||
      frameBytes < 0 ||
      !Number.isSafeInteger(metadataBytes) ||
      metadataBytes < 0 ||
      frameBytes > MAX_QUEUED_MESSAGE_FRAME_BYTES ||
      metadataBytes > MAX_QUEUED_MESSAGE_METADATA_BYTES ||
      messages.length > MAX_QUEUED_MESSAGES - this.messageCountValue ||
      frameBytes > MAX_QUEUED_MESSAGE_FRAME_BYTES - this.frameBytesValue ||
      metadataBytes >
        MAX_QUEUED_MESSAGE_METADATA_BYTES - this.metadataBytesValue
    ) {
      return false;
    }
    if (messages.length === 0) return true;
    this.batches.push({ messages, frameBytes, metadataBytes });
    this.messageCountValue += messages.length;
    this.frameBytesValue += frameBytes;
    this.metadataBytesValue += metadataBytes;
    return true;
  }

  /** Transfer queue ownership to one synchronous main-thread dispatch. */
  drain(): Message[] {
    const batches = this.drainBatches();
    const messages: Message[] = [];
    for (const batch of batches) {
      for (const message of batch) messages.push(message);
    }
    return messages;
  }

  /** Release accounting while preserving original websocket frame windows. */
  drainBatches(): readonly (readonly Message[])[] {
    const batches = this.batches.map((batch) => batch.messages);
    this.reset();
    return batches;
  }

  reset(): void {
    this.batches.length = 0;
    this.frameBytesValue = 0;
    this.metadataBytesValue = 0;
    this.messageCountValue = 0;
  }
}
