import type { BoundedMessageQueue } from "./boundedMessageQueue";
import type { Message } from "./WebsocketMessages";

/** Leave part of a 60 Hz frame for React, layout and user input. */
export const MESSAGE_QUEUE_SLICE_MS = 8;

/** Yield between complete wire frames so preflight/commit stay atomic. A
 * single expensive frame must finish, but a burst cannot monopolize a paint. */
export function processMessageQueueSlice(
  queue: BoundedMessageQueue,
  apply: (messages: readonly Message[]) => boolean,
  now: () => number = () => performance.now(),
  budgetMs = MESSAGE_QUEUE_SLICE_MS,
): boolean {
  const started = now();
  let batch: readonly Message[] | undefined;
  while ((batch = queue.dequeueBatch()) !== undefined) {
    if (!apply(batch)) return false;
    if (queue.messageCount === 0) return false;
    if (now() - started >= budgetMs) return true;
  }
  return false;
}
