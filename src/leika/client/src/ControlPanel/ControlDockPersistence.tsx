import * as React from "react";

import { useDock } from "../dock/DockContext";
import * as ops from "../dock/layoutOps";
import { type DockLayout, type PanelId } from "../dock/types";
import {
  browserControlDockStorage,
  controlDockLayoutStorageKey,
  readControlDockLayout,
  reconcileControlDockLayout,
  RESTORE_SETTLE_MS,
  writeControlDockLayout,
  type ControlDockLayoutStorage,
} from "./controlDockPersistenceModel";
import { controlsSection } from "./SettingsPanelController";

function controlGroup(
  layout: DockLayout,
  controlPanelId: PanelId,
): DockLayout["groups"][string] | null {
  const groupId = ops.findPanelGroup(layout, controlPanelId);
  if (groupId === null) return null;
  const group = layout.groups[groupId];
  return group.panelIds.length === 1 ? group : null;
}

/** Restore and continuously save the desktop dock for one server workspace.
 *
 * The workspace message arrives before the server's GUI components, while
 * draggable tab panels register through React effects. Restoration therefore
 * waits for the registry/layout to settle briefly, then reconciles once. Until
 * that point writes are held back so the empty connecting layout cannot
 * overwrite the saved one.
 */
export function ControlDockPersistence({
  server,
  workspaceId,
  controlPanelId,
  storage = browserControlDockStorage(),
}: {
  server: string;
  workspaceId: string | null;
  controlPanelId: PanelId;
  storage?: ControlDockLayoutStorage | null;
}) {
  const dock = useDock();
  const [readyEpoch, noteReady] = React.useReducer((value) => value + 1, 0);
  const storageKey =
    workspaceId === null
      ? null
      : controlDockLayoutStorageKey(server, workspaceId);
  const panelSignature = Object.keys(dock.panels).sort().join("\n");
  const pending = React.useRef<{
    storageKey: string;
    layout: DockLayout;
  } | null>(null);
  const writableKey = React.useRef<string | null>(null);

  React.useLayoutEffect(() => {
    writableKey.current = null;
    pending.current = null;
    if (storageKey === null) return;

    const stored = readControlDockLayout(storage, storageKey);
    if (stored === null) {
      writableKey.current = storageKey;
      // Re-run the observing effect even though the layout itself did not
      // change while the workspace identity arrived.
      noteReady();
    } else {
      pending.current = { storageKey, layout: stored };
    }
  }, [storage, storageKey]);

  React.useLayoutEffect(() => {
    const restore = pending.current;
    if (
      storageKey === null ||
      restore === null ||
      restore.storageKey !== storageKey
    ) {
      return;
    }

    const applyRestore = () => {
      if (pending.current !== restore) return;
      const next = reconcileControlDockLayout(
        restore.layout,
        dock.layout,
        dock.panels,
      );
      const group = controlGroup(next, controlPanelId);
      pending.current = null;
      writableKey.current = storageKey;

      if (group === null) {
        // A valid generic dock layout can still be the wrong kind of layout
        // for this surface. Keep the live configured panel instead.
        writeControlDockLayout(storage, storageKey, dock.layout);
        return;
      }

      if (group.collapsed === true) controlsSection.close();
      else controlsSection.open();
      dock.api.apply(() => next);
      // apply is a no-op when storage already equals the live layout, so write
      // explicitly rather than relying only on the observing effect below.
      writeControlDockLayout(storage, storageKey, next);
    };

    const allStoredPanelsRegistered = Object.values(
      restore.layout.groups,
    ).every((group) =>
      group.panelIds.every((panelId) => dock.panels[panelId] !== undefined),
    );
    if (allStoredPanelsRegistered) {
      // The normal reload path: restore before these registered panels paint,
      // so an immediate click cannot land on a temporary default layout.
      applyRestore();
      return;
    }

    // A saved panel may genuinely have been removed by a newer server GUI.
    // Briefly allow the replay to register late panels before pruning them.
    const timer = globalThis.setTimeout(applyRestore, RESTORE_SETTLE_MS);
    return () => globalThis.clearTimeout(timer);
  }, [
    controlPanelId,
    dock.api,
    dock.layout,
    dock.panels,
    panelSignature,
    storage,
    storageKey,
  ]);

  React.useEffect(() => {
    if (
      storageKey !== null &&
      pending.current === null &&
      writableKey.current === storageKey
    ) {
      writeControlDockLayout(storage, storageKey, dock.layout);
    }
  }, [dock.layout, readyEpoch, storage, storageKey]);

  return null;
}
