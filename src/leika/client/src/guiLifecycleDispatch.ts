import type { GuiActions } from "./ControlPanel/GuiState";
import type { Message } from "./WebsocketMessages";

type GuiLifecycleActions = Pick<
  GuiActions,
  "declareTab" | "updateTab" | "removeGui" | "removeModal"
>;

/** Route flat GUI lifecycle messages without discarding compact tab tombstones. */
export function dispatchGuiLifecycleMessage(
  message: Message,
  actions: GuiLifecycleActions,
): boolean {
  switch (message.type) {
    case "GuiCloseModalMessage":
      actions.removeModal(
        message.uuid,
        message.removed_uuids,
        message.removed_tab_uuids,
      );
      return true;
    case "GuiTabMessage":
      actions.declareTab(message);
      return true;
    case "GuiTabUpdateMessage":
      actions.updateTab(message);
      return true;
    case "GuiRemoveMessage":
      actions.removeGui(
        message.uuid,
        message.removed_uuids,
        message.removed_tab_uuids,
      );
      return true;
    default:
      return false;
  }
}
