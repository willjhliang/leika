import React from "react";
import { Card } from "../components/ui/card";
import { HoverScrollText } from "../components/HoverScrollText";
import { guiLabelClassName } from "../components/guiLabelStyles";
import { cn } from "../lib/utils";
import { useViewer } from "../ViewerContext";
import type { GridRect, GridSpec } from "./gridLayout";
import { panePositionStyle, paneTitle } from "./workspaceGeometry";
import { displayedViewportPage } from "./viewportSelectors";
import { ViewportPaneRenderer } from "./ViewportPaneRenderer";
import { ViewportPaneLoadingOverlay } from "./ViewportPaneLoadingOverlay";

/** Keep the content offset and the pane's title bar at the same height. */
const PANE_TITLE_BAR_PX = 24;

export function ViewportPaneHost({
  pageId,
  paneId,
  rect,
  grid,
  geometryTransition,
  isDragging,
  motionEnabled,
  onHeaderPointerDown,
  onHeaderKeyDown,
}: {
  pageId: string | null;
  paneId: string;
  rect: GridRect | null;
  grid: GridSpec;
  geometryTransition: string | undefined;
  isDragging: boolean;
  motionEnabled: boolean;
  onHeaderPointerDown: (
    event: React.PointerEvent<HTMLElement>,
    paneId: string,
  ) => void;
  onHeaderKeyDown: (
    event: React.KeyboardEvent<HTMLElement>,
    paneId: string,
  ) => void;
}) {
  const viewer = useViewer();
  const pane = viewer.useViewport(
    (state) => displayedViewportPage(state, pageId)?.panes[paneId],
  );
  const showPaneTitles = viewer.useSettings((state) => state.showPaneTitles);
  const [isHovered, setIsHovered] = React.useState(false);
  // Keyboard users can focus the header without hovering; keep it visible.
  const [isFocused, setIsFocused] = React.useState(false);
  if (pane === undefined) return null;

  const isHiddenHost = rect === null;
  const title = paneTitle(pane);
  const loading = pane.refreshPending !== undefined ? true : pane.props.loading;
  const isLoading = loading !== false;
  return (
    <Card
      data-viewport-pane={isHiddenHost ? undefined : paneId}
      role="region"
      aria-hidden={isHiddenHost || undefined}
      aria-busy={isLoading || undefined}
      className={cn(
        // Panes tile the canvas edge to edge, so they get neither rounding nor
        // a ring: Card's ring is drawn OUTSIDE its box, which put every pane's
        // outline a pixel into its neighbour instead of on its own edge, and
        // rounded corners let the canvas show through at each junction. The
        // divider owns the seam line; the canvas owns the colour behind it.
        "isolate min-h-0 min-w-0 overflow-hidden rounded-none ring-0",
        isHiddenHost && "gap-0 bg-background py-0",
      )}
      style={{
        ...(isHiddenHost
          ? {
              position: "absolute" as const,
              left: 0,
              top: 0,
              width: 1,
              height: 1,
              visibility: "hidden" as const,
              pointerEvents: "none" as const,
            }
          : panePositionStyle(rect, grid)),
        minWidth: 0,
        minHeight: 0,
        transition: isHiddenHost ? undefined : geometryTransition,
      }}
    >
      <div
        data-viewport-pane-content={paneId}
        style={{
          position: "absolute",
          inset: 0,
          // With titles on, the bar is a real top bar and the content starts
          // beneath it; off, the bar overlays the content instead.
          top: !isHiddenHost && showPaneTitles ? PANE_TITLE_BAR_PX : 0,
          minWidth: 0,
          minHeight: 0,
          overflow: "hidden",
        }}
      >
        <div
          data-viewport-pane-renderer
          inert={isLoading || undefined}
          // Keep renderer-owned stacking below the sibling loading surface;
          // otherwise a high-z child such as Plotly's modebar can outrank it.
          style={{ position: "absolute", inset: 0, zIndex: 0 }}
        >
          <ViewportPaneRenderer pane={pane} />
        </div>
        {loading === false ? null : (
          <ViewportPaneLoadingOverlay loading={loading} />
        )}
      </div>

      {!isHiddenHost && (
        <button
          type="button"
          data-viewport-pane-header={paneId}
          data-viewport-pane-title={paneId}
          title={title}
          aria-label={
            "Drag " +
            title +
            " onto another pane: its center swaps, and an edge splits. Shift plus arrow keys swap directionally."
          }
          onPointerDown={(event) => onHeaderPointerDown(event, paneId)}
          tabIndex={0}
          aria-keyshortcuts="Shift+ArrowLeft Shift+ArrowRight Shift+ArrowUp Shift+ArrowDown"
          aria-roledescription="movable split pane"
          onKeyDown={(event) => onHeaderKeyDown(event, paneId)}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          // Hover tracks the bar itself, not the whole pane: when titles are
          // hidden, only a pointer over the strip the bar occupies reveals it.
          onPointerEnter={() => setIsHovered(true)}
          onPointerLeave={() => setIsHovered(false)}
          // Control-panel chrome on a pane: the panel's card surface, square corners
          // (every corner of the bar sits on a pane seam), and the muted
          // field-label type the panel's rows use. Focus is border-only, like
          // every other control.
          className={cn(
            "absolute inset-x-0 top-0 z-20 flex items-center rounded-none border border-transparent bg-card px-2 text-sm outline-none select-none focus-visible:border-ring",
            guiLabelClassName,
          )}
          style={{
            height: PANE_TITLE_BAR_PX,
            // A drag still hides it whatever the setting says: the header is
            // the thing being dragged, and the drag preview stands in for it.
            opacity:
              (showPaneTitles || isHovered || isFocused) && !isDragging ? 1 : 0,
            transition: motionEnabled ? "opacity 250ms ease-in-out" : undefined,
            cursor: isDragging ? "grabbing" : "grab",
            touchAction: "none",
          }}
        >
          <HoverScrollText>{title}</HoverScrollText>
        </button>
      )}
    </Card>
  );
}
