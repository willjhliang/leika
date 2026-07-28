// Shared drag-handle UI primitives, used across the dock's views: the grip
// pill drawn inside every handle, the hover-highlighted icon button docked in
// handle bars, and the stack handle bar that drags a whole group stack
// (floating multi-group window header / docked column handle).

import { MinusIcon, PlusIcon } from "lucide-react";
import React from "react";
import { Button } from "../components/ui/button";
import { Separator } from "../components/ui/separator";
import { CARD_INSET_TOP_BAR } from "./cardInset";

/** Centered grip line drawn inside every drag handle (grip bars, stack
 * handles, the vertical minimized strip). */
export function GripPill({
  width = "2.5em",
  opacity = 0.5,
}: {
  width?: string;
  opacity?: number;
}) {
  return <Separator style={{ width, opacity }} />;
}

/** Hover-highlighted icon button used inside handles (per-group minimize on
 * the grip bar, minimize-all on a stack handle, expand on a vertical strip
 * cell). `placement` overrides the default right-edge absolute anchoring.
 *
 * Two pointer modes:
 * - Default: swallows pointerdown so pressing the button can't arm the
 *   handle's drag gesture; a click activates directly.
 * - `dragThrough`: the press FLOWS to the parent handle, whose click-vs-drag
 *   arbitration decides -- motion drags the panel, a motionless release
 *   activates (the parent passes the activation as its onClick). The button
 *   itself only activates on synthetic clicks (element.click() from tests /
 *   assistive tech, event.detail === 0); real pointer clicks are the
 *   parent's, so the toggle can't fire twice. */
export function HandleIconButton({
  label,
  title,
  expanded,
  onActivate,
  attrs,
  placement,
  dragThrough = false,
  children,
}: {
  label: string;
  title: string;
  expanded: boolean;
  onActivate: () => void;
  attrs: Record<string, string>;
  placement?: React.CSSProperties;
  dragThrough?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Button
      {...attrs}
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-label={label}
      aria-expanded={expanded}
      title={title}
      onPointerDown={
        dragThrough ? undefined : (event) => event.stopPropagation()
      }
      onClick={(event) => {
        if (dragThrough && event.detail !== 0) return;
        event.stopPropagation();
        onActivate();
      }}
      style={{
        ...(placement ?? {
          position: "absolute",
          right: 0,
          // The bar's CONTENT band, which is not its padding box once the bar
          // has taken on a card inset (see CARD_INSET_TOP_BAR) -- and absolute
          // insets are measured from the padding box.
          top: "var(--handle-inset-top, 0px)",
          bottom: 0,
          width: "1.7em",
        }),
      }}
    >
      {children}
    </Button>
  );
}

/** Slim header bar that drags a whole stack of groups: a floating multi-group
 * window or a docked pure column. Body-colored so it reads as the stack's
 * *container*, distinct from the child groups' gray grip bars; the bottom rule
 * keeps it visible against the first child's grip bar.
 *
 * With `onToggle`, the bar gets a minimize-ALL button: it minimizes every
 * child group (tagging the ones that were expanded), and -- when every child
 * is minimized -- expands them back to that remembered mix (see
 * minimizeStack/expandStack in layoutOps). */
export function StackHandleBar({
  onPointerDown,
  attrs,
  collapsed = false,
  onToggle,
  narrow = false,
  insetTop = false,
}: {
  onPointerDown: (event: React.PointerEvent<HTMLDivElement>) => void;
  attrs: Record<string, string>;
  /** Derived stack state: true when EVERY child group is minimized. */
  collapsed?: boolean;
  onToggle?: () => void;
  /** The bar sits on a minimized STRIP (~36px wide): there is no room for the
   * centered pill next to the button, so the button alone fills the bar. */
  narrow?: boolean;
  /** The bar sits against the top of a card that has given up its `py` for it:
   * take that inset as padding, so the band above the bar drags too (see
   * CARD_INSET_TOP in cardInset). */
  insetTop?: boolean;
}) {
  return (
    <div
      {...attrs}
      onPointerDown={onPointerDown}
      className={`relative flex min-h-8 shrink-0 cursor-grab items-center justify-center touch-none${
        insetTop ? ` ${CARD_INSET_TOP_BAR}` : ""
      }`}
    >
      {!narrow && <GripPill width="3em" opacity={0.6} />}
      {onToggle !== undefined && (
        <HandleIconButton
          attrs={{ "data-dock-minimize-all": "true" }}
          label={collapsed ? "Expand all panels" : "Minimize all panels"}
          title={collapsed ? "Expand all" : "Minimize all"}
          expanded={!collapsed}
          onActivate={onToggle}
          placement={
            narrow
              ? { position: "relative", width: "100%", height: "100%" }
              : undefined
          }
        >
          {collapsed ? <PlusIcon /> : <MinusIcon />}
        </HandleIconButton>
      )}
    </div>
  );
}
