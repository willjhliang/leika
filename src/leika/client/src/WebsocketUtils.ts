import React from "react";
import { Message } from "./WebsocketMessages";
import { ViewerContext, ViewerContextContents } from "./ViewerContext";

export const GUI_MESSAGE_THROTTLE_MS = 50;

/** Easier, hook version of makeThrottledMessageSender.
 *
 * Memoized so the returned ``{send}`` keeps a stable identity across
 * renders: callers wire ``send`` into ``useCallback`` dep arrays and into
 * context provider values, where a fresh object every render would defeat
 * memoization downstream and cause unrelated re-renders. The pending
 * throttle timer is also cleared on unmount so a teardown doesn't leave a
 * dangling closure pinning the viewer. */
export function useThrottledMessageSender(throttleMilliseconds: number) {
  const viewer = React.useContext(ViewerContext)!;
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
    parts.push(...Object.keys(message.updates).sort());
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
) {
  let readyToSend = true;
  let pendingTimer: ReturnType<typeof setTimeout> | null = null;
  const pending = new Map<string, Message>();
  let eventCounter = 0;

  /** Send everything that waited out the window. Returns whether anything
   * went, which is what decides if a fresh window opens behind it. */
  function emitPending(): boolean {
    const sendMessage = viewer.mutable.current.sendMessage;
    if (pending.size === 0) return false;
    const queued = [...pending.values()];
    pending.clear();
    queued.forEach((message) => sendMessage(message));
    return true;
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
    const sendMessage = viewer.mutable.current.sendMessage;
    if (readyToSend) {
      sendMessage(message);
      openWindow();
      return;
    }
    const key =
      options?.coalesce === false
        ? `${message.type}:${(eventCounter += 1)}`
        : coalescingKey(message);
    pending.set(key, message);
  }

  function cancel() {
    if (pendingTimer !== null) {
      clearTimeout(pendingTimer);
      pendingTimer = null;
    }
    readyToSend = true;
    pending.clear();
  }
  return { send, cancel };
}
