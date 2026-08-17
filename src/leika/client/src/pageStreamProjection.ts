import type { Message } from "./WebsocketMessages";
import type { ViewportState } from "./viewport/ViewportState";

function viewportPayloadPageId(message: Message): string | null {
  switch (message.type) {
    case "ViewportImageMessage":
    case "ViewportMatplotlibMessage":
    case "ViewportPlotlyMessage":
    case "ViewportViserMessage":
    case "ViewportPaneUpdateMessage":
    case "ViewportPaneRemoveMessage":
    case "ViewportPaneSnapshotMessage":
      return message.page_id;
    default:
      return null;
  }
}

/** Drop stale page frames before they can consume preflight or state budgets. */
export function filterPageStreamMessages(
  messages: readonly Message[],
  state: ViewportState,
): readonly Message[] {
  const expected = state.pageStream;
  let acceptingPageId = expected?.accepting ? expected.pageId : null;
  return messages.filter((message) => {
    if (message.type === "PageStreamBeginMessage") {
      const matches =
        expected !== null &&
        state.activePageId === message.page_id &&
        expected.pageId === message.page_id &&
        expected.generation === message.generation;
      // Every begin is a route boundary. A late generation must close the
      // batch-local gate so its following payload cannot enter the new stream.
      acceptingPageId = matches ? message.page_id : null;
      return matches;
    }
    const pageId = viewportPayloadPageId(message);
    return pageId === null || pageId === acceptingPageId;
  });
}
