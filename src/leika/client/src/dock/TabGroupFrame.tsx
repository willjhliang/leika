// Renders one tab group: stock shadcn tab chrome plus mounted panel bodies.
// Docking, dragging, resizing, and FLIP animation remain model concerns.

import { MinusIcon, PlusIcon } from "lucide-react";
import React from "react";

import { CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Collapsible, CollapsibleContent } from "../components/ui/collapsible";
import { ScrollArea } from "../components/ui/scroll-area";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../components/ui/tabs";
import { cn } from "../lib/utils";
import { prefersReducedMotion } from "../utils/motion";
import {
  CARD_INSET_BOTTOM,
  CARD_INSET_BOTTOM_OVERLAP,
  CARD_INSET_TOP,
  CARD_INSET_TOP_BAR,
} from "./cardInset";
import { GripPill, HandleIconButton } from "./handles";
import { toggleGroupVisibility, useDock } from "./DockContext";
import { DOUBLE_CLICK_MS, PanelSpec, TAB_GLIDE_MS, TabGroup } from "./types";

const PanelBody = React.memo(function PanelBody({
  panel,
  fill,
  maxContentHeight,
  inheritContentPadding,
}: {
  panel: PanelSpec | undefined;
  fill: boolean;
  maxContentHeight?: number;
  inheritContentPadding: boolean;
}) {
  if (panel?.fullBleed === true) {
    return (
      <div
        className="w-full"
        style={
          fill
            ? {
                flexGrow: 1,
                minHeight: 0,
                display: "flex",
                flexDirection: "column",
              }
            : undefined
        }
      >
        {panel.render()}
      </div>
    );
  }

  const content = inheritContentPadding ? (
    (panel?.render() ?? null)
  ) : (
    <CardContent>{panel?.render() ?? null}</CardContent>
  );
  return (
    <ScrollArea
      data-dock-panel-scroll-body
      className={cn(
        // A scroll viewport clips at its padding box, and a first row whose
        // ink rides above its box -- a slider thumb on a track pushed up by
        // its annotations -- would lose its crown. The room has to come from
        // outside the viewport: the area slides up under the header's slack
        // and pads its top by the same amount, so every row keeps its
        // position while the clip edge moves above the overflowing ink.
        "-mt-1 [&_[data-slot=scroll-area-viewport]]:pt-1",
        fill
          ? "min-h-0 w-full flex-1"
          : "w-full [&_[data-slot=scroll-area-viewport]]:max-h-[inherit]",
      )}
      style={fill ? undefined : { maxHeight: maxContentHeight }}
    >
      {content}
    </ScrollArea>
  );
});

function GripBar({
  collapsed,
  onToggle,
  startDrag,
  insetTop,
}: {
  collapsed: boolean;
  onToggle: () => void;
  startDrag: (
    event: React.PointerEvent<HTMLDivElement>,
    opts?: { onClick?: () => void; expandOnDrag?: boolean },
  ) => void;
  insetTop: boolean;
}) {
  return (
    <CardHeader
      data-dock-griphandle
      className={`relative flex min-h-8 shrink-0 cursor-grab flex-row items-center justify-center touch-none select-none${
        insetTop ? ` ${CARD_INSET_TOP_BAR}` : ""
      }`}
      onPointerDown={(event) => {
        const fromButton =
          (event.target as HTMLElement).closest("[data-dock-minimize]") !==
          null;
        startDrag(
          event,
          fromButton
            ? { onClick: onToggle, expandOnDrag: collapsed }
            : undefined,
        );
      }}
    >
      <GripPill />
      <HandleIconButton
        attrs={{ "data-dock-minimize": "true" }}
        label={collapsed ? "Expand panel" : "Minimize panel"}
        title={collapsed ? "Expand" : "Minimize"}
        expanded={!collapsed}
        onActivate={onToggle}
        dragThrough
      >
        {collapsed ? <PlusIcon /> : <MinusIcon />}
      </HandleIconButton>
    </CardHeader>
  );
}

export function TabGroupFrame({
  group,
  fill = true,
  maxContentHeight,
  stripDragsGroup = true,
  inheritContentPadding = false,
  insetTop = false,
  insetBottom = false,
  dockAreaId,
  dockAreaMinHeight,
}: {
  group: TabGroup;
  fill?: boolean;
  maxContentHeight?: number;
  stripDragsGroup?: boolean;
  /** Embedded dock areas already live inside their host surface's CardContent.
   * Independent floating/docked groups leave this false and own CardContent. */
  inheritContentPadding?: boolean;
  /** Set by the frame's host when this frame sits against the top / bottom edge
   * of a card that has given up its `py` for it -- see CARD_INSET_TOP. A stack
   * hands them to its first and last member; a lone frame gets both. */
  insetTop?: boolean;
  insetBottom?: boolean;
  /** When this group is a populated nested dock area, the group root is also
   * the area's drop target. Empty areas retain their own placeholder root. */
  dockAreaId?: string;
  dockAreaMinHeight?: React.CSSProperties["minHeight"];
}) {
  const dock = useDock();
  const { panels } = dock;
  const dimmed = dock.draggingGroupId === group.id;
  const collapsed = group.collapsed ?? false;
  const unmergeable = group.panelIds.some(
    (panelId) => panels[panelId]?.unmergeable === true,
  );

  const stripRef = React.useRef<HTMLDivElement>(null);
  const previousLefts = React.useRef<Map<string, number>>(new Map());
  const orderKey = JSON.stringify(group.panelIds);
  React.useLayoutEffect(() => {
    const strip = stripRef.current;
    if (strip === null) return;
    const currentIds = new Set<string>();
    strip.querySelectorAll<HTMLElement>("[data-dock-tab]").forEach((tab) => {
      const id = tab.getAttribute("data-dock-tab");
      if (id === null) return;
      currentIds.add(id);
      const left = tab.offsetLeft;
      const previous = previousLefts.current.get(id);
      previousLefts.current.set(id, left);
      if (
        id === dock.draggingTabId ||
        previous === undefined ||
        previous === left ||
        prefersReducedMotion()
      ) {
        return;
      }
      tab.style.transition = "none";
      tab.style.transform = `translateX(${previous - left}px)`;
      requestAnimationFrame(() => {
        tab.style.transition = `transform ${TAB_GLIDE_MS}ms ease`;
        tab.style.transform = "";
      });
    });
    previousLefts.current.forEach((_, id) => {
      if (!currentIds.has(id)) previousLefts.current.delete(id);
    });
  }, [orderKey, dock.draggingTabId]);

  // A handle click toggles collapse; two in quick succession put the panel back
  // where it belongs. The first click still toggles immediately -- deferring it
  // to watch for a second would put the double-click delay on every collapse --
  // so the pair is a toggle and its undo, landing on the state it started from
  // with the panel restored. `onResetLayout` is the panel's own; a panel that
  // has no notion of home leaves the pair as the two toggles it is made of.
  // Negative infinity, not 0: `performance.now()` counts from page load, so a
  // zero would make the first click of the first half-second read as the
  // second half of a double-click.
  const lastHandleClick = React.useRef(Number.NEGATIVE_INFINITY);
  const handleClick = () => {
    const now = performance.now();
    const isDouble = now - lastHandleClick.current < DOUBLE_CLICK_MS;
    lastHandleClick.current = isDouble ? Number.NEGATIVE_INFINITY : now;
    // Every click does the panel's own thing, or folds the group when the panel
    // has no opinion. The second click of a pair therefore UNDOES the first --
    // a toggle and its undo -- leaving the reset as the only lasting effect.
    if (!toggleGroupVisibility(dock, group.id)) dock.toggleCollapsed(group.id);
    if (isDouble) panels[group.activeId]?.onResetLayout?.();
  };

  const renderPanelBody = (panelId: string) => (
    <PanelBody
      panel={panels[panelId]}
      fill={fill}
      maxContentHeight={maxContentHeight}
      inheritContentPadding={inheritContentPadding}
    />
  );
  const rootClassName = "flex min-h-0 w-full min-w-0 flex-col overflow-hidden";
  const rootStyle: React.CSSProperties = {
    flexGrow: collapsed ? 0 : fill ? 1 : undefined,
    flexShrink: collapsed ? 0 : fill ? 1 : undefined,
    flexBasis: collapsed ? "auto" : fill ? 0 : undefined,
    minHeight: dockAreaMinHeight ?? 0,
    opacity: dimmed ? 0.4 : 1,
    transition:
      fill && !prefersReducedMotion()
        ? "flex-grow 200ms ease, flex-basis 200ms ease"
        : undefined,
  };

  if (unmergeable) {
    const panel = panels[group.activeId];
    const body = renderPanelBody(group.activeId);
    const collapsibleBody = (
      <Collapsible open={!collapsed}>
        <CollapsibleContent keepMounted>{body}</CollapsibleContent>
      </Collapsible>
    );
    const handleTestId = panel?.testId && `${panel.testId}-handle`;
    // The gap separating the header from the body is the header's, not the
    // root's: a press in it is a press on the title bar, and the header can
    // only be pressed where the header IS. A collapsed panel has no body to be
    // separated from -- nor does one reporting an empty body, which is how a
    // disconnected control panel renders -- so there the header runs on to the
    // bottom of the card instead, and the gap would otherwise hang below it as
    // whitespace the card's own padding does not balance.
    const headerIsLast = collapsed || panel?.bodyIsEmpty === true;
    const headerBottom = headerIsLast
      ? insetBottom
        ? ` ${CARD_INSET_BOTTOM_OVERLAP}`
        : ""
      : " pb-2";
    return (
      <div
        data-dock-area={dockAreaId}
        data-dock-group={group.id}
        data-dock-collapsed={collapsed ? "true" : undefined}
        data-testid={collapsed ? handleTestId : undefined}
        className={`${rootClassName}${
          insetBottom ? ` ${CARD_INSET_BOTTOM}` : ""
        }`}
        style={rootStyle}
      >
        <CardHeader
          ref={stripRef}
          data-dock-strip={group.id}
          data-dock-header={group.id}
          data-testid={collapsed ? undefined : handleTestId}
          title={
            panel?.titleNode ? undefined : (panel?.title ?? group.activeId)
          }
          className={`flex flex-row items-center${
            insetTop ? ` ${CARD_INSET_TOP}` : ""
          }${headerBottom}${
            stripDragsGroup ? " cursor-grab touch-none select-none" : ""
          }`}
          onPointerDown={(event) => {
            if (stripDragsGroup) {
              dock.startGroupDrag(event, group.id, {
                onClick: handleClick,
              });
            }
          }}
        >
          {panel?.titleNode ? (
            panel.titleNode
          ) : (
            <CardTitle>{panel?.title ?? group.activeId}</CardTitle>
          )}
        </CardHeader>
        {fill ? body : collapsibleBody}
      </div>
    );
  }

  return (
    <Tabs
      value={group.activeId}
      onValueChange={(panelId) => dock.activateTab(group.id, panelId)}
      data-dock-area={dockAreaId}
      data-dock-group={group.id}
      data-dock-collapsed={collapsed ? "true" : undefined}
      // With a grip bar, the top inset goes to the bar (a handle, and the thing
      // the band reads as belonging to). Without one there is nothing to hand
      // it to, so the frame keeps it as plain padding.
      className={`${rootClassName} gap-0${
        insetTop && !stripDragsGroup ? ` ${CARD_INSET_TOP}` : ""
      }${insetBottom ? ` ${CARD_INSET_BOTTOM}` : ""}`}
      style={rootStyle}
    >
      {stripDragsGroup && (
        <GripBar
          collapsed={collapsed}
          insetTop={insetTop}
          onToggle={handleClick}
          startDrag={(event, options) =>
            dock.startGroupDrag(event, group.id, options)
          }
        />
      )}
      <TabsList
        ref={stripRef}
        variant="line"
        data-dock-strip={group.id}
        // A strip of panel tabs wraps, so its height is whatever its tabs need
        // -- and `h-auto` has to be marked important to say so. The stock list
        // sets a one-line height from the tabs root above it, which outranks a
        // plain class here: the strip stayed 32px tall while holding two lines
        // of tabs, and since it does not clip, the second line was painted over
        // whatever the panel had below it.
        className="h-auto! w-full flex-wrap justify-start"
        onPointerDown={(event) => {
          if ((event.target as HTMLElement).closest("[data-dock-tab]")) {
            return;
          }
          if (stripDragsGroup) dock.startGroupDrag(event, group.id);
        }}
      >
        {group.panelIds.map((panelId) => {
          const dragging = panelId === dock.draggingTabId;
          const panel = panels[panelId];
          return (
            <TabsTrigger
              key={panelId}
              value={panelId}
              data-dock-tab={panelId}
              title={panel?.title ?? panelId}
              className="max-w-56"
              onPointerDown={(event) =>
                dock.startTabDrag(event, group.id, panelId)
              }
              style={{
                position: dragging ? "relative" : undefined,
                zIndex: dragging ? 5 : undefined,
                opacity: dragging ? 1 : undefined,
              }}
            >
              {panel?.icon !== undefined && (
                <span data-icon="inline-start">{panel.icon}</span>
              )}
              <span className="truncate">{panel?.title ?? panelId}</span>
            </TabsTrigger>
          );
        })}
      </TabsList>
      {group.panelIds.map((panelId) => {
        const panelBody = renderPanelBody(panelId);
        return (
          <TabsContent
            key={panelId}
            value={panelId}
            keepMounted
            className={
              fill
                ? "mt-2 flex min-h-0 flex-1 basis-0 flex-col overflow-hidden"
                : "mt-2 min-h-0"
            }
          >
            {fill ? (
              panelBody
            ) : (
              <Collapsible open={!collapsed}>
                <CollapsibleContent keepMounted>{panelBody}</CollapsibleContent>
              </Collapsible>
            )}
          </TabsContent>
        );
      })}
    </Tabs>
  );
}
