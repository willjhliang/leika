import * as React from "react";

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
 * same strip that cannot. Nothing about how a tab LOOKS is decided here. */
export type TabStripDrag = {
  /** The dock group the strip stands for, for the dock's own hit-testing. */
  groupId: string;
  /** The tab currently under a drag, which is raised above its neighbours. */
  draggingId: string | null;
  /** A press on the strip itself, away from any tab. */
  onStripPointerDown: (event: React.PointerEvent<HTMLElement>) => void;
  /** A press on one tab: a click activates it, a drag tears it out. */
  onTabPointerDown: (
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
}: {
  tabs: TabStripItem[];
  /** Left out, the tabs are fixed in place; given, they can be dragged. */
  drag?: TabStripDrag;
}) {
  return (
    <TabsList
      ref={drag?.stripRef}
      variant="line"
      className="h-auto! w-full min-w-0 flex-wrap justify-start"
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
            className="max-w-56 min-w-fit"
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
