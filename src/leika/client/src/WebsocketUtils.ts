import React from "react";
import { Message } from "./WebsocketMessages";
import { useViewer, ViewerContextContents } from "./ViewerContext";
import { captureSendSession, SendSession } from "./connectionSender";

export const GUI_MESSAGE_THROTTLE_MS = 50;
export const MAX_PENDING_THROTTLED_MESSAGES = 8_192;
export const MAX_PENDING_UNCOALESCED_EVENTS = 1_024;
export const THROTTLED_MESSAGE_OVERFLOW_REASON =
  "The browser's outbound GUI event queue exceeded its safety limit.";

type ThrottleQueueLimits = {
  maxPendingMessages: number;
  maxPendingEvents: number;
};

/** Easier, hook version of makeThrottledMessageSender.
 *
 * Memoized so the returned ``{send}`` keeps a stable identity across
 * renders: callers wire ``send`` into ``useCallback`` dep arrays and into
 * context provider values, where a fresh object every render would defeat
 * memoization downstream and cause unrelated re-renders. The pending
 * throttle timer is also cleared on unmount so a teardown doesn't leave a
 * dangling closure pinning the viewer. */
export function useThrottledMessageSender(throttleMilliseconds: number) {
  const viewer = useViewer();
  const sender = React.useMemo(
    () => makeThrottledMessageSender(viewer, throttleMilliseconds),
    [viewer, throttleMilliseconds],
  );
  React.useEffect(() => sender.cancel, [sender]);
  return sender;
}

/** What a deferred message is filed under while it waits out the window.
 *
 * Every message the panel sends is addressed to one component and says one
 * kind of thing about it, so the address is the key: a newer value for a
 * slider replaces the last one, which is what makes a drag one message per
 * window rather than one per frame. A hold tick keys on its frequency for the
 * same reason -- it carries nothing but the fact of itself, so the extras
 * inside a window are the rate cap doing its job. */
function coalescingKey(message: Message): string {
  const parts: string[] = [message.type];
  if ("uuid" in message) parts.push(message.uuid);
  if (message.type === "GuiUpdateMessage") {
    for (const key of Object.keys(message.updates).sort()) parts.push(key);
  } else if (message.type === "GuiButtonHoldMessage") {
    parts.push(String(message.frequency));
  }
  return parts.join(":");
}

/** Returns a function for sending messages, with automatic throttling.
 *
 * One message goes out per window per THING -- see coalescingKey -- and the
 * rest wait for the window to close. Not one message per window full stop:
 * the panel shares a single sender across every control it draws, so a single
 * pending slot meant a press could overwrite the edit that came before it and
 * the edit would never be sent at all. Typing into a field and immediately
 * submitting the form around it lost the typing.
 *
 * Deferred messages keep the order they were first filed in, so an edit and
 * the submit that commits it arrive that way round.
 *
 * ``send`` takes ``coalesce: false`` for a message that is an EVENT rather
 * than a state: a button press is a thing that happened, and two of them
 * inside one window are two presses, not one. Anything that would rather
 * arrive late than not at all belongs here.
 *
 * Returns ``cancel`` to clear any pending throttle timer (e.g. on unmount);
 * after ``cancel`` the sender is still usable and will fire the next message
 * immediately. */
export function makeThrottledMessageSender(
  viewer: ViewerContextContents,
  throttleMilliseconds: number,
  limits: ThrottleQueueLimits = {
    maxPendingMessages: MAX_PENDING_THROTTLED_MESSAGES,
    maxPendingEvents: MAX_PENDING_UNCOALESCED_EVENTS,
  },
) {
  if (
    !Number.isSafeInteger(limits.maxPendingMessages) ||
    limits.maxPendingMessages < 1 ||
    !Number.isSafeInteger(limits.maxPendingEvents) ||
    limits.maxPendingEvents < 1 ||
    limits.maxPendingEvents > limits.maxPendingMessages
  ) {
    throw new Error("Invalid throttled-message queue limits.");
  }
  let readyToSend = true;
  let pendingTimer: ReturnType<typeof setTimeout> | null = null;
  const pending = new Map<
    string | object,
    { message: Message; session: SendSession }
  >();
  let pendingEventCount = 0;
  let blockedSender: SendSession["sendMessage"] | null = null;

  function clearPendingWindow() {
    if (pendingTimer !== null) {
      clearTimeout(pendingTimer);
      pendingTimer = null;
    }
    readyToSend = true;
    pending.clear();
    pendingEventCount = 0;
  }

  /** Losing a local event would silently change application semantics. Close
   * the affected transport instead, and refuse more work from that exact
   * sender until connection replacement (or explicit owner cleanup). */
  function failOverflow(session: SendSession) {
    blockedSender = session.sendMessage;
    clearPendingWindow();
    viewer.mutable.current.failConnection(THROTTLED_MESSAGE_OVERFLOW_REASON);
  }

  /** Send everything that waited out the window. Returns whether anything
   * went, which is what decides if a fresh window opens behind it. */
  function emitPending(): boolean {
    if (pending.size === 0) return false;
    const queued = [...pending.values()];
    pending.clear();
    pendingEventCount = 0;
    let emitted = false;
    for (const { message, session } of queued) {
      if (!session.isCurrent()) continue;
      session.sendMessage(message);
      emitted = true;
    }
    return emitted;
  }

  function openWindow() {
    readyToSend = false;
    pendingTimer = setTimeout(() => {
      pendingTimer = null;
      readyToSend = true;
      if (emitPending()) openWindow();
    }, throttleMilliseconds);
  }

  function send(message: Message, options?: { coalesce?: boolean }) {
    const session = captureSendSession(viewer.mutable.current);
    if (blockedSender !== null) {
      if (session.sendMessage === blockedSender) return;
      blockedSender = null;
    }
    if (readyToSend) {
      session.sendMessage(message);
      openWindow();
      return;
    }
    const isEvent = options?.coalesce === false;
    if (isEvent && pendingEventCount >= limits.maxPendingEvents) {
      failOverflow(session);
      return;
    }
    // An object key can never collide with a server-controlled string key and
    // naturally gives every non-coalescing event its own bounded slot.
    const key: string | object = isEvent ? {} : coalescingKey(message);
    if (!pending.has(key) && pending.size >= limits.maxPendingMessages) {
      failOverflow(session);
      return;
    }
    pending.set(key, { message, session });
    if (isEvent) pendingEventCount += 1;
  }

  function cancel() {
    clearPendingWindow();
    blockedSender = null;
  }
  return { send, cancel };
}
