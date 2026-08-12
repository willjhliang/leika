import * as ops from "../dock/layoutOps";
import { normalizeDockLayout } from "../dock/persistedLayout";
import { type DockLayout, type PanelRegistry } from "../dock/types";

export interface ControlDockLayoutStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const STORAGE_KEY_PREFIX = "leika.control-dock.layout.v1:";
export const RESTORE_SETTLE_MS = 50;

export function controlDockLayoutStorageKey(
  server: string,
  workspaceId: string,
): string {
  return STORAGE_KEY_PREFIX + server + ":" + workspaceId;
}

export function browserControlDockStorage(): ControlDockLayoutStorage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function readControlDockLayout(
  storage: ControlDockLayoutStorage | null,
  storageKey: string,
): DockLayout | null {
  if (storage === null) return null;
  try {
    const serialized = storage.getItem(storageKey);
    return serialized === null
      ? null
      : normalizeDockLayout(JSON.parse(serialized));
  } catch {
    return null;
  }
}

export function writeControlDockLayout(
  storage: ControlDockLayoutStorage | null,
  storageKey: string,
  layout: DockLayout,
): void {
  if (storage === null) return;
  try {
    storage.setItem(storageKey, JSON.stringify(layout));
  } catch {
    // A read-only/full store must not make the dock itself unusable.
  }
}

/** Reconcile a valid saved layout with panels registered on this page.
 *
 * Removed server panels are pruned with the same operation the live dock uses.
 * Panels introduced since the layout was saved keep the home placement they
 * already received during initial GUI hydration, normally their nested area.
 */
export function reconcileControlDockLayout(
  stored: DockLayout,
  current: DockLayout,
  panels: PanelRegistry,
): DockLayout {
  let next = stored;
  for (const group of Object.values(stored.groups)) {
    for (const panelId of group.panelIds) {
      if (panels[panelId] === undefined) {
        next = ops.removePanel(next, panelId);
      }
    }
  }

  for (const panelId of Object.keys(panels)) {
    if (ops.findPanelGroup(next, panelId) !== null) continue;
    const currentGroupId = ops.findPanelGroup(current, panelId);
    if (currentGroupId === null) continue;
    const location = ops.findGroupLocation(current, currentGroupId);
    if (location?.kind === "area") {
      const currentGroup = current.groups[currentGroupId];
      next = ops.addPanelToArea(
        next,
        location.areaId,
        panelId,
        currentGroup.panelIds.indexOf(panelId),
      );
    } else if (location?.kind === "floating") {
      const window = current.floating.find(
        (candidate) => candidate.id === location.windowId,
      );
      if (window !== undefined) {
        next = ops.addFloatingPanel(
          next,
          panelId,
          window.x,
          window.y,
          window.width,
          window.height,
        ).layout;
      }
    }
  }
  return next;
}
