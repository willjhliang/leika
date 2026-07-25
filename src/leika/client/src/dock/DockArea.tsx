// A nested "dockable area": a flat tab group embedded in a panel's body.
//
// Unlike the old standalone version (which used native HTML5 drag-and-drop and
// its own local state), this is a FIRST-CLASS participant in the dock model: its
// tab group lives in the shared layout, so dropping panels in, reordering tabs,
// tearing a panel out (to float, or to merge with the host/parent panel), and
// dropping a whole snapped stack (which collapses into a series of tabs) all
// reuse the exact same layout ops, hit-testing, and pointer-drag controller as
// everything else -- there is no difference between "standard" and "nested"
// panels.
//
// Placement: put <DockArea areaId="..."/> in a panel's render(). The area's
// group and its initial panels are seeded in the layout (layout.areas + a
// TabGroup in layout.groups). The DockManager registers this container as a drop
// target by its `data-dock-area` attribute.

import React from "react";
import { useDock } from "./DockContext";
import { TabGroupFrame } from "./TabGroupFrame";

export function DockArea({
  areaId,
  minHeight = 120,
  fill = false,
  inheritContentPadding = false,
}: {
  areaId: string;
  /** Minimum height so an empty area still presents a comfortable drop zone. */
  minHeight?: number | string;
  /** Fill the host's available height (e.g. when the area is a panel's entire
   * body). Otherwise the area sizes to content. */
  fill?: boolean;
  /** Reuse a CardContent inset already owned by the host panel. */
  inheritContentPadding?: boolean;
}) {
  const dock = useDock();
  const area = dock.areas[areaId];
  const group = area ? dock.groups[area.group] : undefined;
  const style: React.CSSProperties = fill
    ? { flexGrow: 1, minHeight: 0 }
    : { minHeight };

  if (group === undefined || group.panelIds.length === 0) {
    return (
      <div
        data-dock-area={areaId}
        className="flex w-full items-center justify-center overflow-hidden px-4 text-center text-sm text-muted-foreground"
        style={style}
      >
        Drop a panel here
      </div>
    );
  }

  // A populated group's root is also the area's drop target. Fill uses
  // flex-grow rather than height:100%, so auto-height floating windows still
  // size to their content instead of collapsing to zero.
  return (
    <TabGroupFrame
      group={group}
      fill={fill}
      stripDragsGroup={false}
      inheritContentPadding={inheritContentPadding}
      dockAreaId={areaId}
      dockAreaMinHeight={style.minHeight}
    />
  );
}
