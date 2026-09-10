import type { GuiState } from "./GuiState";
import { shallowArrayEqual } from "../utils/shallowArrayEqual";

type OrderState = Pick<
  GuiState,
  "guiUuidSetFromContainerUuid" | "guiOrderFromUuid"
>;

/** One container's ordered children, stable until their displayed order changes.
 *
 * Structural updates share the membership records of untouched containers, but
 * replace the global order map. Keep a local order snapshot so another panel's
 * insertion does not sort or rerender this panel and every control inside it.
 * Unrelated store updates only compare references and allocate nothing. */
export function createGuiContainerOrderSelector(containerUuid: string) {
  let previousMembers: Record<string, true> | undefined;
  let previousOrder: OrderState["guiOrderFromUuid"] | undefined;
  let members: string[] = [];
  let orders: number[] = [];
  let ordered: string[] = [];

  return (state: OrderState): string[] => {
    const nextMembers = state.guiUuidSetFromContainerUuid[containerUuid];
    const nextOrder = state.guiOrderFromUuid;
    if (nextMembers === previousMembers && nextOrder === previousOrder) {
      return ordered;
    }

    const membershipChanged = nextMembers !== previousMembers;
    const orderChanged =
      membershipChanged ||
      members.some((uuid, index) => nextOrder[uuid] !== orders[index]);
    previousMembers = nextMembers;
    previousOrder = nextOrder;
    if (!orderChanged) return ordered;

    if (membershipChanged) members = Object.keys(nextMembers ?? {});
    orders = members.map((uuid) => nextOrder[uuid]);
    // Start from membership order, preserving insertion order for equal ranks
    // even after a previous update temporarily gave those children other ranks.
    const next = members.slice().sort((a, b) => nextOrder[a] - nextOrder[b]);
    if (!shallowArrayEqual(ordered, next)) ordered = next;
    return ordered;
  };
}
