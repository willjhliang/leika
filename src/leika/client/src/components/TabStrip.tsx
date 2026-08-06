import { GripVerticalIcon } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";

/** One tab, however it is being drawn: a GUI tab group's own tab, or a panel
 * the dock is holding in a group. */
export type TabStripItem = {
  id: string;
  label: string;
  /** Already-rendered icon markup or node, drawn before the label. */
  icon?: React.ReactNode;
};

/** What a strip needs to be dragged, when there is a dock to drag it into.
 *
 * Its presence is the whole difference between the two kinds of tab group: a
 * strip given this can be torn apart and rearranged, and one without it is the
 * same strip that cannot. Nothing about how a tab LOOKS is decided here.
 *
 * Two kinds of dragging meet on a tab, split by where the press lands. The
 * tab's FACE is part of the strip's surface: dragging it moves the container
 * the strip is the title of (the window, or the group out of its dock), and
 * clicking it does what clicking a title does. The tab's GRIP -- the handle
 * that appears on hover, as a list entry's does -- is how the TAB itself is
 * dragged: reordered along the strip, or torn out into its own window. */
export type TabStripDrag = {
  /** The dock group the strip stands for, for the dock's own hit-testing. */
  groupId: string;
  /** The tab currently under a drag, which is raised above its neighbours. */
  draggingId: string | null;
  /** A press on the strip's whitespace, away from any tab. */
  onStripPointerDown: (event: React.PointerEvent<HTMLElement>) => void;
  /** A press on a tab's face: the container's own drag and click. */
  onTabPointerDown: (
    event: React.PointerEvent<HTMLElement>,
    id: string,
  ) => void;
  /** A press on a tab's grip: reorder the tab, or tear it out. */
  onTabGripPointerDown: (
    event: React.PointerEvent<HTMLElement>,
    id: string,
  ) => void;
  /** The strip element, which the dock measures to glide tabs into place. */
  stripRef: React.Ref<HTMLDivElement>;
};

/**
 * The row of tabs above a tab group, wherever the group is being drawn.
 *
 * There is one of these because there is one kind of tab: a GUI tab group in
 * the docked control panel and the same group in a sidebar were two components
 * that had drifted into two different-looking things -- one a filled pill strip
 * that scrolled its overflow away silently, the other an underlined strip that
 * wrapped -- and which one an author got was decided by a panel-chrome setting
 * with no visible connection to it.
 *
 * The strip wraps rather than scrolling: a tab whose words are cut off at an
 * edge, with no scrollbar to say there is more, is a tab nobody can read. It is
 * as tall as the tabs it holds, marked important because the stock list sets a
 * one-line height from the tabs root above it.
 */
export function TabStrip({
  tabs,
  drag,
  className,
}: {
  tabs: TabStripItem[];
  /** Left out, the tabs are fixed in place; given, they can be dragged. */
  drag?: TabStripDrag;
  /** Extra layout the host hangs on the strip -- a card inset it has taken
   * over, say. Look-and-feel stays here. */
  className?: string;
}) {
  return (
    <TabsList
      ref={drag?.stripRef}
      variant="line"
      className={cn(
        "h-auto! w-full min-w-0 flex-wrap justify-start",
        // Where the strip is a group's handle, it reads as one: the grab
        // cursor on its whitespace, with each tab keeping its own pointer.
        drag !== undefined &&
          "cursor-grab touch-none select-none [&_[data-leika-tab]]:cursor-pointer",
        className,
      )}
      data-leika-tabs-list
      data-dock-strip={drag?.groupId}
      onPointerDown={
        drag === undefined
          ? undefined
          : (event) => {
              // A press that landed on a tab is that tab's to handle.
              if ((event.target as HTMLElement).closest("[data-dock-tab]")) {
                return;
              }
              drag.onStripPointerDown(event);
            }
      }
    >
      {tabs.map((tab) => {
        const dragging = drag?.draggingId === tab.id;
        return (
          <TabsTrigger
            key={tab.id}
            value={tab.id}
            title={tab.label}
            // A lone tab is the group's whole title and takes the whole row;
            // the cap exists so that in a CROWD no one tab hogs the strip.
            className={cn("group/tab min-w-fit", tabs.length > 1 && "max-w-56")}
            data-leika-tab
            data-dock-tab={drag === undefined ? undefined : tab.id}
            onPointerDown={
              drag === undefined
                ? undefined
                : (event) => drag.onTabPointerDown(event, tab.id)
            }
            style={
              dragging
                ? { position: "relative", zIndex: 5, opacity: 1 }
                : undefined
            }
          >
            {drag !== undefined && (
              // The tab's own drag handle, off to the side until the pointer
              // is on the tab -- the same reveal a list entry's grip has. A
              // span, not a button: it lives inside the tab's own <button>.
              <span
                data-leika-tab-drag-handle
                title="Drag to move this tab"
                className={cn(
                  "pointer-events-none absolute top-0 left-0 flex h-full w-4 cursor-grab touch-none items-center justify-center opacity-0",
                  "text-muted-foreground hover:text-foreground",
                  "group-hover/tab:pointer-events-auto group-hover/tab:opacity-100",
                )}
                onPointerDown={(event) => {
                  // The grip's press is the TAB's drag; without this it would
                  // bubble into the face's container drag.
                  event.stopPropagation();
                  drag.onTabGripPointerDown(event, tab.id);
                }}
              >
                <GripVerticalIcon className="size-3.5" />
              </span>
            )}
            {tab.icon}
            {/* A tab is not worth widening the strip for: past `max-w-56` the
                label gives way. `TabsTrigger` is a flex box, so the ellipsis
                has to be asked for on a box inside it. */}
            <span className="truncate">{tab.label}</span>
          </TabsTrigger>
        );
      })}
    </TabsList>
  );
}
