// The desktop control panel: one card over the canvas. Its header drags it to
// float anywhere, or to the left or right edge, where it docks and the canvas
// gives up its width. A click on the header collapses it to the header and
// back; a double-click sends it home. Its side edges resize its width.

import React from "react";

import { Card, CardContent, CardHeader } from "../components/ui/card";
import { ScrollArea } from "../components/ui/scroll-area";
import { motionExceedsThreshold } from "../dragUtils";
import { cn } from "../lib/utils";
import { bindPointerGesture, tryCapture, tryRelease } from "../pointerGesture";
import { useViewer } from "../ViewerContext";
import { ControlPanelContents, PanelHeader } from "./ControlPanel";
import {
  type ControlPanelLayout,
  FLOATING_INSET_PX,
  useControlPanel,
} from "./controlPanelLayout";
import { MAX_CONTROL_WIDTH_PX, MIN_CONTROL_WIDTH_PX } from "./controlWidth";
import { ROOT_GUI_CONTAINER_ID } from "./guiConstants";
import { SettingsButton } from "./SettingsPane";

type Edge = "left" | "right";

/** A drag released this close to a canvas edge docks the panel there. */
const EDGE_ZONE_PX = 48;
/** Two header clicks this close together are a double-click. */
const DOUBLE_CLICK_MS = 400;
/** A floating panel keeps this much of its header on the canvas. */
const KEEP_HEADER_PX = 40;
/** A resize always leaves this much of the canvas visible. */
const KEEP_CANVAS_PX = 100;

const clamp = (value: number, low: number, high: number) =>
  Math.max(low, Math.min(high, value));

export function ControlPanelFrame() {
  const panel = useControlPanel();
  const layout = panel.store();
  // Without any GUI -- connecting, inactive, or a server that added none --
  // the panel is its header alone.
  const hasGenerated = useViewer().useGui(
    (state) =>
      Object.keys(
        state.guiUuidSetFromContainerUuid[ROOT_GUI_CONTAINER_ID] ?? {},
      ).length > 0,
  );
  const cardRef = React.useRef<HTMLDivElement>(null);
  const [dropEdge, setDropEdge] = React.useState<Edge | null>(null);
  const lastClick = React.useRef(Number.NEGATIVE_INFINITY);
  // The gesture in flight, cancelled if the panel unmounts under it.
  const gesture = React.useRef<(() => void) | null>(null);
  React.useEffect(() => () => gesture.current?.(), []);

  const docked = layout.placement !== "floating";
  const showBody = hasGenerated && !layout.collapsed;

  /** Follow one pointer until it lifts. Escape, or losing the pointer, puts
   * back the layout the gesture started from. */
  const follow = (
    event: React.PointerEvent<HTMLElement>,
    onMove: (move: PointerEvent) => void,
    onRelease: () => void,
  ) => {
    gesture.current?.();
    const element = event.currentTarget;
    const before = panel.store.get();
    // Captured so the gesture keeps its moves over pane iframes.
    tryCapture(element, event.pointerId);
    const end = (cancelled: boolean) => {
      detach();
      tryRelease(element, event.pointerId);
      gesture.current = null;
      setDropEdge(null);
      if (cancelled) panel.preview(before);
      else onRelease();
    };
    const detach = bindPointerGesture(
      onMove,
      (_event, cancelled) => end(cancelled),
      event.pointerId,
    );
    gesture.current = () => end(true);
  };

  const canvasRect = () =>
    cardRef.current!.parentElement!.getBoundingClientRect();

  const onHeaderPointerDown = (event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    // The header is a handle: no text selection, and focus stays put.
    event.preventDefault();
    const start: [number, number] = [event.clientX, event.clientY];
    const before = panel.store.get();
    const canvas = canvasRect();
    const card = cardRef.current!.getBoundingClientRect();
    // Floating offsets that keep the header under the pointer, wherever the
    // panel starts.
    const startRight = canvas.right - card.right;
    const startTop = card.top - canvas.top;
    let dragging = false;
    let edge: Edge | null = null;
    follow(
      event,
      (move) => {
        const point: [number, number] = [move.clientX, move.clientY];
        if (!dragging && !motionExceedsThreshold(start, point)) return;
        dragging = true;
        edge =
          point[0] - canvas.left < EDGE_ZONE_PX
            ? "left"
            : canvas.right - point[0] < EDGE_ZONE_PX
              ? "right"
              : null;
        setDropEdge(edge);
        panel.preview({
          placement: "floating",
          right: clamp(
            startRight - (point[0] - start[0]),
            0,
            canvas.width - before.width,
          ),
          top: clamp(
            startTop + (point[1] - start[1]),
            0,
            canvas.height - KEEP_HEADER_PX,
          ),
        });
      },
      () => {
        if (dragging) {
          lastClick.current = Number.NEGATIVE_INFINITY;
          panel.save(edge === null ? {} : { placement: edge });
          return;
        }
        const now = performance.now();
        if (now - lastClick.current < DOUBLE_CLICK_MS) {
          lastClick.current = Number.NEGATIVE_INFINITY;
          panel.reset();
        } else {
          lastClick.current = now;
          panel.save({ collapsed: !before.collapsed });
        }
      },
    );
  };

  const onResizePointerDown =
    (side: Edge) => (event: React.PointerEvent<HTMLElement>) => {
      if (event.button !== 0) return;
      event.preventDefault();
      const startX = event.clientX;
      const before = panel.store.get();
      const canvas = canvasRect();
      const card = cardRef.current!.getBoundingClientRect();
      const maxWidth = clamp(
        canvas.width - KEEP_CANVAS_PX,
        MIN_CONTROL_WIDTH_PX,
        MAX_CONTROL_WIDTH_PX,
      );
      follow(
        event,
        (move) => {
          const delta = move.clientX - startX;
          const width = clamp(
            before.width + (side === "left" ? -delta : delta),
            MIN_CONTROL_WIDTH_PX,
            maxWidth,
          );
          const change: Partial<ControlPanelLayout> = { width };
          // A floating panel is placed by its right edge, which only a
          // right-side resize moves.
          if (side === "right" && !docked) {
            change.right = Math.max(
              0,
              canvas.right - card.right - (width - card.width),
            );
          }
          panel.preview(change);
        },
        () => panel.save(),
      );
    };

  return (
    <>
      {dropEdge !== null && (
        // Where the panel will dock if released here.
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 z-5 bg-accent opacity-80"
          style={{ [dropEdge]: 0, width: layout.width }}
        />
      )}
      <Card
        ref={cardRef}
        data-testid="control-panel"
        data-leika-placement={layout.placement}
        data-leika-collapsed={layout.collapsed || undefined}
        className={cn(
          // A grid rather than the card's flex column: the body row then
          // scrolls inside whatever height the card is given or capped at.
          "absolute z-10 grid max-w-full grid-rows-[auto_minmax(0,1fr)] gap-0 overflow-visible py-0",
          showBody && "pb-(--card-spacing)",
          // Docked, the card is flush with the edge and tiles against the
          // canvas; floating, or folded to its header over the canvas, it is
          // lifted off it.
          docked && "rounded-none",
          (!docked || layout.collapsed) && "shadow-md",
        )}
        style={
          docked
            ? {
                top: 0,
                bottom: layout.collapsed ? undefined : 0,
                [layout.placement]: 0,
                width: layout.width,
              }
            : {
                // A shrinking window pulls a saved position back into view.
                right: `clamp(0px, ${layout.right}px, calc(100% - ${layout.width}px))`,
                top: `clamp(0px, ${layout.top}px, calc(100% - ${KEEP_HEADER_PX}px))`,
                width: layout.width,
                maxHeight: `calc(100% - ${2 * FLOATING_INSET_PX}px)`,
              }
        }
      >
        <CardHeader
          data-testid="control-panel-handle"
          className={cn(
            "flex cursor-grab touch-none flex-row items-center pt-(--card-spacing) select-none active:cursor-grabbing",
            showBody ? "pb-2" : "pb-(--card-spacing)",
          )}
          onPointerDown={onHeaderPointerDown}
        >
          <PanelHeader actions={<SettingsButton />} />
        </CardHeader>
        {/* Hidden rather than unmounted, so half-typed values survive a
            collapse. The scroll area rides up under the header's slack and
            pads its top by as much, giving first-row ink that rises above its
            box room inside the clip. */}
        <ScrollArea
          hidden={!showBody}
          className="-mt-1 min-h-0 [&>[data-slot=scroll-area-viewport]]:pt-1"
        >
          <CardContent>
            <ControlPanelContents />
          </CardContent>
        </ScrollArea>
        {(["left", "right"] as const)
          .filter((side) => side !== layout.placement)
          .map((side) => (
            <div
              key={side}
              data-testid={`control-panel-resize-${side}`}
              className={cn(
                "absolute inset-y-0 z-10 w-2 cursor-ew-resize touch-none",
                side === "left" ? "-left-1" : "-right-1",
              )}
              onPointerDown={onResizePointerDown(side)}
            />
          ))}
      </Card>
    </>
  );
}
