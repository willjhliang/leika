import * as React from "react";

import { ViewerContext } from "../ViewerContext";
import { shallowObjectKeysEqual } from "../utils/shallowObjectKeysEqual";

export function useContainerIsEmpty(containerUuid: string): boolean {
  const viewer = React.useContext(ViewerContext)!;
  const guiIdSet = viewer.useGui(
    (state) => state.guiUuidSetFromContainerUuid[containerUuid],
    shallowObjectKeysEqual,
  );
  return guiIdSet === undefined || Object.keys(guiIdSet).length === 0;
}
