import React from "react";
import { Button } from "../components/ui/button";
import { Separator } from "../components/ui/separator";
import {
  GRID_EPSILON,
  type DividerGeometry,
  type GridSpec,
} from "./gridLayout";
import { gridLinePx } from "./workspaceGeometry";

const DIVIDER_HIT_SIZE_PX = 24;
/** Draw the line after its grid boundary to keep it on a whole pixel. */
const DIVIDER_LINE_SIZE_PX = 1;

export function ViewportDivider({
  divider,
  grid,
  geometryTransition,
  beforeTitle,
  afterTitle,
  onPointerDown,
  onKeyDown,
}: {
  divider: DividerGeometry;
  grid: GridSpec;
  geometryTransition: string | undefined;
  beforeTitle: string;
  afterTitle: string;
  onPointerDown: (
    event: React.PointerEvent<HTMLElement>,
    divider: DividerGeometry,
  ) => void;
  onKeyDown: (
    event: React.KeyboardEvent<HTMLElement>,
    divider: DividerGeometry,
  ) => void;
}) {
  const { cellWidth, cellHeight } = grid;
  const vertical = divider.direction === "row";
  const index = divider.dividerIndex;
  const minimum = Math.ceil(
    divider.coordinate -
      divider.childSpans[index] +
      divider.childMinimums[index] -
      GRID_EPSILON,
  );
  const maximum = Math.floor(
    divider.coordinate +
      divider.childSpans[index + 1] -
      divider.childMinimums[index + 1] +
      GRID_EPSILON,
  );
  const lineStyle: React.CSSProperties = {
    position: "absolute",
    // On the grid line, not centred in the hit area: the hit area is an even
    // 24px, so centring a 1px line inside it lands on a half pixel.
    left: vertical ? DIVIDER_HIT_SIZE_PX / 2 : 0,
    top: vertical ? 0 : DIVIDER_HIT_SIZE_PX / 2,
    width: vertical ? DIVIDER_LINE_SIZE_PX : "100%",
    height: vertical ? "100%" : DIVIDER_LINE_SIZE_PX,
    pointerEvents: "none",
  };

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      role="separator"
      data-viewport-divider={divider.key}
      data-viewport-divider-direction={divider.direction}
      aria-label={"Resize " + beforeTitle + " and " + afterTitle + " panes"}
      aria-orientation={vertical ? "vertical" : "horizontal"}
      aria-valuemin={minimum}
      aria-valuemax={maximum}
      aria-valuenow={divider.coordinate}
      aria-valuetext={(vertical ? "column " : "row ") + divider.coordinate}
      aria-keyshortcuts={
        vertical
          ? "ArrowLeft ArrowRight Shift+ArrowLeft Shift+ArrowRight"
          : "ArrowUp ArrowDown Shift+ArrowUp Shift+ArrowDown"
      }
      onPointerDown={(event) => onPointerDown(event, divider)}
      onKeyDown={(event) => onKeyDown(event, divider)}
      // An invisible 24px grab strip. It drops Button's transparent border,
      // because the line inside is positioned against the PADDING box and that
      // 1px border offset it from the grid line and trimmed both ends. The
      // ghost variant's hover fill is dropped too: hovering recolours the
      // divider itself rather than painting a band the width of the strip.
      //
      // Crossing dividers overlap by a pixel, and the one painted last wins.
      // Raising the active one keeps its highlight unbroken along its whole
      // length instead of notched wherever another divider crosses it. The
      // z-index lives here rather than in `style` so the hover variant can
      // reach it; inline styles would outrank it.
      className="group/divider z-30 border-0 hover:z-40 hover:bg-transparent focus-visible:z-40 dark:hover:bg-transparent"
      style={{
        position: "absolute",
        left: vertical
          ? gridLinePx(divider.coordinate, cellWidth) - DIVIDER_HIT_SIZE_PX / 2
          : gridLinePx(divider.nodeRect.x, cellWidth),
        top: vertical
          ? gridLinePx(divider.nodeRect.y, cellHeight)
          : gridLinePx(divider.coordinate, cellHeight) -
            DIVIDER_HIT_SIZE_PX / 2,
        width: vertical
          ? DIVIDER_HIT_SIZE_PX
          : gridLinePx(divider.nodeRect.x + divider.nodeRect.width, cellWidth) -
            gridLinePx(divider.nodeRect.x, cellWidth),
        height: vertical
          ? gridLinePx(
              divider.nodeRect.y + divider.nodeRect.height,
              cellHeight,
            ) - gridLinePx(divider.nodeRect.y, cellHeight)
          : DIVIDER_HIT_SIZE_PX,
        cursor: vertical ? "col-resize" : "row-resize",
        touchAction: "none",
        transition: geometryTransition,
      }}
    >
      {/* Backdrop and line share one rect: the line's tokens are translucent
          in dark mode, so without an opaque layer beneath it the divider would
          tint whatever pane content sits behind it and read as a different
          colour over every pane. Two elements rather than stacking the token
          as a background image over a background colour, because only
          background-COLOR can transition. */}
      <span aria-hidden="true" className="bg-background" style={lineStyle} />
      <Separator
        aria-hidden="true"
        orientation={vertical ? "vertical" : "horizontal"}
        // The same two tokens an input's border uses: `--input` at rest,
        // `--ring` once the divider is hovered or focused. Keyboard resizing
        // needs the focus half, since the strip itself draws nothing.
        className="bg-input transition-colors group-hover/divider:bg-ring group-focus-visible/divider:bg-ring"
        style={lineStyle}
      />
    </Button>
  );
}
