import { randomUuid } from "../utils/randomUuid";
import { DockLayout, DockNode } from "./types";

export type DockIdPrefix = "group" | "node" | "window";
export type DockIdAllocator = (prefix: DockIdPrefix) => string;

/**
 * Produce a collision-resistant id. UUIDs keep ids generated after restoring a
 * persisted layout independent from the module-local lifetime of this page.
 */
export function freshDockId(prefix: DockIdPrefix): string {
  return `${prefix}-${randomUuid()}`;
}

function collectNodeIds(node: DockNode | null, ids: Set<string>): void {
  if (node === null) return;
  ids.add(node.id);
  if (node.type === "split") {
    node.children.forEach((child) => collectNodeIds(child, ids));
  }
}

/**
 * Allocate ids that are also checked against every id already present in a
 * layout. The optional source makes collision handling deterministic in tests.
 */
export function createDockIdAllocator(
  layout?: DockLayout,
  source: DockIdAllocator = freshDockId,
): DockIdAllocator {
  const occupied = new Set<string>();
  if (layout !== undefined) {
    Object.entries(layout.groups).forEach(([key, group]) => {
      occupied.add(key);
      occupied.add(group.id);
    });
    collectNodeIds(layout.docked.left, occupied);
    collectNodeIds(layout.docked.right, occupied);
    layout.floating.forEach((window) => occupied.add(window.id));
  }

  return (prefix) => {
    let id: string;
    do id = source(prefix);
    while (occupied.has(id));
    occupied.add(id);
    return id;
  };
}
