// A fully-minimized docked column rendered as a narrow vertical strip: one
// cell per leaf, with an upright icon and a rotated (book-spine) title.
// Click expands; drag floats the group (the same click-vs-drag gesture as the
// unmergeable header). Renders every fully-minimized docked column: stranded
// inside a row split or spanning a whole region root.

import { PlusIcon } from "lucide-react";
import React from "react";
import { Card } from "../components/ui/card";
import { Separator } from "../components/ui/separator";
import { toggleGroupVisibility, useDock } from "./DockContext";
import { HandleIconButton } from "./handles";
import { DockEdge, DockNode, NodeId, TabGroup, testIdForGroup } from "./types";
import { collectLeaves } from "./layoutOps";

export function VerticalMinimizedColumn({
  node,
  edge,
}: {
  node: DockNode;
  edge: DockEdge;
}) {
  const dock = useDock();
  const leaves = collectLeaves(node);
  return (
    <Card
      className="min-h-0 min-w-0 flex-1 overflow-hidden"
      style={{
        flexGrow: 1,
        minWidth: 0,
        minHeight: 0,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      {leaves.map(({ id, group }, i) => {
        const g = dock.groups[group];
        if (g === undefined) return null;
        return (
          <React.Fragment key={id}>
            {i > 0 && <Separator />}
            <VerticalMinimizedCell nodeId={id} edge={edge} group={g} />
          </React.Fragment>
        );
      })}
    </Card>
  );
}

function VerticalMinimizedCell({
  nodeId,
  edge,
  group,
}: {
  nodeId: NodeId;
  edge: DockEdge;
  group: TabGroup;
}) {
  const dock = useDock();
  // Unfolding a strip means the same as clicking the handle: the panel
  // decides what comes back, and only a panel with no opinion is folded by
  // the group's own flag.
  const unfoldGroup = (groupId: string) => {
    if (!toggleGroupVisibility(dock, groupId)) dock.toggleCollapsed(groupId);
  };
  const title = group.panelIds
    .map((p) => dock.panels[p]?.title ?? p)
    .join(" / ");
  const icon = dock.panels[group.activeId]?.icon;
  // Same `-handle` test id a collapsed FLOATING group gets (see TabGroupFrame),
  // so a panel stays addressable by the id its spec declared no matter which
  // minimized form it currently takes.
  const testId = testIdForGroup(dock.panels, group);
  // The tab strip draws its rule on the side AWAY from the content; rotated
  // 90 degrees, that's the side facing the canvas (left for a right-docked
  // strip, right for a left-docked one).
  return (
    // data-dock-leaf/-edge on the cell so collectTargets offers it as a docked
    // target; hitTest's collapsed branch gives it the 5-way drop zones.
    <div
      data-dock-leaf={nodeId}
      data-dock-edge={edge}
      style={{ flexGrow: 1, minHeight: 0, display: "flex", width: "100%" }}
    >
      <div
        data-dock-group={group.id}
        data-dock-collapsed="true"
        data-testid={testId && `${testId}-handle`}
        title={title}
        onPointerDown={(event: React.PointerEvent<HTMLDivElement>) =>
          dock.startGroupDrag(event, group.id, {
            onClick: () => unfoldGroup(group.id),
            // A drag that starts on the expand (+) button tears out the FULL
            // panel (expand-then-drag); from anywhere else the cell drags as
            // the minimized stub it shows.
            expandOnDrag:
              (event.target as HTMLElement).closest("[data-dock-minimize]") !==
              null,
          })
        }
        className="flex w-full touch-none select-none flex-col items-center overflow-hidden"
        style={{
          cursor: "grab",
          opacity: dock.draggingGroupId === group.id ? 0.4 : 1,
        }}
      >
        {/* The expand button is the cap and handle here: motion drags the
        panel, while a motionless click expands it in place. */}
        <HandleIconButton
          attrs={{ "data-dock-minimize": "true" }}
          label="Expand panel"
          title="Expand"
          expanded={false}
          onActivate={() => unfoldGroup(group.id)}
          dragThrough
          // Static placement filling the cap (not bar-anchored).
          placement={{ width: "100%", height: "1.7em" }}
        >
          <PlusIcon />
        </HandleIconButton>
        {/* Panel icon stays UPRIGHT (icons don't read rotated). */}
        {icon !== undefined && (
          <div className="mt-1 flex shrink-0 items-center justify-center text-muted-foreground">
            {icon}
          </div>
        )}
        {/* Book-spine orientation (top-to-bottom, rotated clockwise): the
        portable vertical-text form -- sideways-lr isn't supported in Safari.
        Dimmed like the strip's secondary chrome -- a minimized title is a
        wayfinding label, not content. */}
        <div className="mt-2 min-h-0 overflow-hidden text-ellipsis whitespace-nowrap pb-2 text-sm font-medium text-muted-foreground [text-orientation:mixed] [writing-mode:vertical-rl]">
          {title}
        </div>
      </div>
    </div>
  );
}
