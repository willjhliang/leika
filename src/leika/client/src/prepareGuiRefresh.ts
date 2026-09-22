import type { Message } from "./WebsocketMessages";
import type { ViewerContextContents } from "./ViewerContext";

let sequence = 0;

/** Clear before the outbound throttle; receipts travel with the final queued value. */
export function prepareGuiRefresh(
  viewer: ViewerContextContents,
  message: Message,
): Message {
  if (message.type !== "GuiUpdateMessage" || !("value" in message.updates))
    return message;
  // Works on tailnet HTTP origins where crypto.randomUUID is unavailable.
  const requestId = `${Date.now()}-${++sequence}-${Math.random()}`;
  return viewer.viewportActions.invalidateForInput(message.uuid, requestId)
    ? { ...message, type: "GuiRefreshMessage", request_id: requestId }
    : message;
}
