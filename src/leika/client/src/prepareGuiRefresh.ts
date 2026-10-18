import type { Message } from "./WebsocketMessages";
import type { ViewerContextContents } from "./ViewerContext";
import { randomUuid } from "./utils/randomUuid";

/** Clear before the outbound throttle; receipts travel with the final queued value. */
export function prepareGuiRefresh(
  viewer: ViewerContextContents,
  message: Message,
): Message {
  if (message.type !== "GuiUpdateMessage" || !("value" in message.updates))
    return message;
  const requestId = randomUuid();
  return viewer.viewportActions.invalidateForInput(message.uuid, requestId)
    ? { ...message, type: "GuiRefreshMessage", request_id: requestId }
    : message;
}
