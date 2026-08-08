import { useViewer } from "../ViewerContext";
import { ROOT_GUI_CONTAINER_ID } from "./guiConstants";

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
  const viewer = useViewer();
  return viewer.useGui(
    (state) =>
      Object.keys(
        state.guiUuidSetFromContainerUuid[ROOT_GUI_CONTAINER_ID] ?? {},
      ).length > 0,
  );
}
