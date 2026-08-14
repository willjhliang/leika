import {
  isGuiComponentMessage,
  type GuiComponentMessage,
  type GuiModalMessage,
  type GuiTabMessage,
  type GuiTabUpdateMessage,
  type Message,
  type RegisterCommandMessage,
} from "./WebsocketMessages";

export interface GuiUpdate {
  uuid: string;
  updates: Record<string, unknown>;
}

export type MessageErrorReporter = (message: Message, error: unknown) => void;

const reportMessageError: MessageErrorReporter = (message, error) => {
  console.error(`Failed to process Leika message '${message.type}':`, error);
};

export interface BatchedMessageHandlers {
  guiComponents: (messages: readonly GuiComponentMessage[]) => void;
  modals: (messages: readonly GuiModalMessage[]) => void;
  commands: (messages: readonly RegisterCommandMessage[]) => void;
  tabs?: (messages: readonly (GuiTabMessage | GuiTabUpdateMessage)[]) => void;
  /** Contiguous updates commit before the next lifecycle message so UUID
   * replacement/removal keeps chronological wire semantics. */
  guiUpdates?: (updates: ReadonlyMap<string, Record<string, unknown>>) => void;
}

/** Preflight each original wire frame before state/resource side effects. */
export function processPreflightedMessageBatches(
  batches: readonly (readonly Message[])[],
  preflight: (messages: readonly Message[]) => string | null,
  apply: (messages: readonly Message[]) => string | null,
  failConnection: (reason: string) => void,
): boolean {
  for (const messages of batches) {
    const failure = preflight(messages);
    if (failure !== null) {
      failConnection(failure);
      return false;
    }
    const applyFailure = apply(messages);
    if (applyFailure !== null) {
      failConnection(applyFailure);
      return false;
    }
  }
  return true;
}

/** Dispatch one websocket batch without letting one bad message drop the rest. */
export function dispatchMessageBatch(
  messages: readonly Message[],
  handleMessage: (message: Message) => GuiUpdate | undefined,
  reportError: MessageErrorReporter = reportMessageError,
  batched?: BatchedMessageHandlers,
): Map<string, Record<string, unknown>> {
  const guiUpdates = new Map<string, Record<string, unknown>>();
  const guiUpdateMessages: Message[] = [];
  let pending:
    | { kind: "gui"; messages: GuiComponentMessage[] }
    | { kind: "modal"; messages: GuiModalMessage[] }
    | { kind: "command"; messages: RegisterCommandMessage[] }
    | {
        kind: "tab";
        messages: (GuiTabMessage | GuiTabUpdateMessage)[];
      }
    | undefined;

  const flush = () => {
    if (pending === undefined || batched === undefined) return;
    const current = pending;
    pending = undefined;
    try {
      if (current.kind === "gui") batched.guiComponents(current.messages);
      else if (current.kind === "modal") batched.modals(current.messages);
      else if (current.kind === "command") {
        batched.commands(current.messages);
      } else {
        batched.tabs?.(current.messages);
      }
    } catch (error) {
      for (const message of current.messages) reportError(message, error);
    }
  };

  const queueBatchable = (message: Message): boolean => {
    if (batched === undefined) return false;
    if (isGuiComponentMessage(message)) {
      if (pending?.kind !== "gui") {
        flush();
        pending = { kind: "gui", messages: [] };
      }
      pending.messages.push(message);
      return true;
    }
    if (message.type === "GuiModalMessage") {
      if (pending?.kind !== "modal") {
        flush();
        pending = { kind: "modal", messages: [] };
      }
      pending.messages.push(message);
      return true;
    }
    if (message.type === "RegisterCommandMessage") {
      if (pending?.kind !== "command") {
        flush();
        pending = { kind: "command", messages: [] };
      }
      pending.messages.push(message);
      return true;
    }
    if (
      batched.tabs !== undefined &&
      (message.type === "GuiTabMessage" ||
        message.type === "GuiTabUpdateMessage")
    ) {
      if (pending?.kind !== "tab") {
        flush();
        pending = { kind: "tab", messages: [] };
      }
      pending.messages.push(message);
      return true;
    }
    return false;
  };

  const flushGuiUpdates = () => {
    if (guiUpdates.size === 0 || batched?.guiUpdates === undefined) return;
    const updates = new Map(guiUpdates);
    guiUpdates.clear();
    const messages = guiUpdateMessages.splice(0);
    try {
      batched.guiUpdates(updates);
    } catch (error) {
      for (const message of messages) reportError(message, error);
    }
  };

  for (const message of messages) {
    if (message.type === "GuiUpdateMessage") {
      // A create batch must be visible before the update that follows it.
      flush();
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
      guiUpdateMessages.push(message);
      continue;
    }

    // Updates belong to the incarnation that existed at this point on the
    // wire. Commit them before any later create/remove/replacement message.
    flushGuiUpdates();
    if (queueBatchable(message)) continue;
    flush();

    try {
      handleMessage(message);
    } catch (error) {
      reportError(message, error);
    }
  }
  flush();
  flushGuiUpdates();

  return guiUpdates;
}
