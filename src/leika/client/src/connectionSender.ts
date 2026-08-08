import type { Message } from "./WebsocketMessages";

export type MessageSender = (message: Message) => void;

type MessageSenderSlot = {
  sendMessage: MessageSender;
};

export type SendSession = {
  sendMessage: MessageSender;
  isCurrent: () => boolean;
};

/** Capture the current sender together with its connection-identity check. */
export function captureSendSession(slot: MessageSenderSlot): SendSession {
  const sendMessage = slot.sendMessage;
  return {
    sendMessage,
    isCurrent: () => slot.sendMessage === sendMessage,
  };
}

/** Install a sender that is valid only while it owns the mutable slot.
 *
 * Disconnecting or connecting again replaces the slot and therefore revokes
 * any copy of this function held by delayed work. Stale work is intentionally
 * ignored: warning for every remaining upload chunk would only add noise after
 * the connection lifecycle has already reported the disconnect. */
export function installConnectionBoundSender(
  slot: MessageSenderSlot,
  sendToConnection: MessageSender,
): MessageSender {
  const boundSender: MessageSender = (message) => {
    if (slot.sendMessage === boundSender) sendToConnection(message);
  };
  slot.sendMessage = boundSender;
  return boundSender;
}
