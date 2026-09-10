import { useViewer } from "../ViewerContext";

export function useContainerIsEmpty(containerUuid: string): boolean {
  const viewer = useViewer();
  // The enclosing folder only depends on emptiness. Adding/reordering a child
  // in a nonempty container must not render its header and popout again.
  return viewer.useGui((state) => {
    const members = state.guiUuidSetFromContainerUuid[containerUuid];
    if (members === undefined) return true;
    for (const uuid in members) {
      if (Object.hasOwn(members, uuid)) return false;
    }
    return true;
  });
}
