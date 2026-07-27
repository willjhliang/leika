import React from "react";

import { ViewerContext } from "../ViewerContext";

// Must match constant in Python.
const ROOT_CONTAINER_ID = "root";

/** True when the root container has any generated GUI to show.
 *
 * Read both by the panel body, which collapses to nothing without it, and by
 * the floating panel's spec, whose frame drops its header/body gap when the
 * body renders nothing -- while the client is connecting, inactive, or simply
 * pointed at a server that has added no GUI.
 *
 * Its own module rather than `ControlPanel.tsx` so that file keeps exporting
 * only components, which is what fast refresh needs to swap them in place. */
export function useShowGenerated(): boolean {
  const viewer = React.useContext(ViewerContext)!;
  return viewer.useGui(
    (state) =>
      Object.keys(state.guiUuidSetFromContainerUuid[ROOT_CONTAINER_ID] ?? {})
        .length > 0,
  );
}
