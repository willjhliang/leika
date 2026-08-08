import type { Message } from "./WebsocketMessages";

export interface GuiUpdate {
  uuid: string;
  updates: Record<string, unknown>;
}

export type MessageErrorReporter = (message: Message, error: unknown) => void;

const reportMessageError: MessageErrorReporter = (message, error) => {
  console.error(`Failed to process Leika message '${message.type}':`, error);
};

/** Dispatch one websocket batch without letting one bad message drop the rest. */
export function dispatchMessageBatch(
  messages: readonly Message[],
  handleMessage: (message: Message) => GuiUpdate | undefined,
  reportError: MessageErrorReporter = reportMessageError,
): Map<string, Record<string, unknown>> {
  const guiUpdates = new Map<string, Record<string, unknown>>();

  for (const message of messages) {
    // Updates are deferred to the end of the batch while removes apply
    // immediately, so an update whose component was removed later in the
    // same batch is legitimate leftover, not an error.
    if (message.type === "GuiRemoveMessage") guiUpdates.delete(message.uuid);

    let result: GuiUpdate | undefined;
    try {
      result = handleMessage(message);
    } catch (error) {
      reportError(message, error);
      continue;
    }
    if (result === undefined) continue;
    guiUpdates.set(result.uuid, {
      ...(guiUpdates.get(result.uuid) ?? {}),
      ...result.updates,
    });
  }

  return guiUpdates;
}
