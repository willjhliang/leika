// Shared drag-handle UI primitives: the hover-highlighted icon button docked
// in handle bars, and the stack handle bar that drags a whole group stack
// (floating multi-group window header / docked column handle).

import { MinusIcon, PlusIcon } from "lucide-react";
import React from "react";
import { Button } from "../components/ui/button";
import { Separator } from "../components/ui/separator";

/** Centered grip line used by the stack handle in this module. */
function GripPill({
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
          top: 0,
          bottom: 0,
          width: "1.7em",
        }),
      }}
    >
      {children}
    </Button>
  );
}

/** Slim handle that drags a whole docked pure COLUMN of groups. A column
 * needs it because its members' strips undock the members one at a time --
 * there is no surface that means "all of them" without this. (A floating
 * stack has no such bar: there, every member strip moves the whole window,
 * and a member leaves by its tab's grip.) Nothing but the pill: drag moves
 * the column, click folds every member away and back
 * (minimizeStack/expandStack remember which were open).
 *
 * `narrow` is the exception: on a fully-minimized ~36px strip the members
 * have no titles to click, so the bar keeps a real expand-all (+) button. */
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
  /** The bar sits on a minimized STRIP (~36px wide): no room for the pill,
   * and no member titles to fold with -- a real (+) button fills the bar. */
  narrow?: boolean;
  /** The bar sits against the top of a card that has given up its `py` for
   * it: take (half of) that inset as padding, the same treatment a member's
   * tab strip gets, so the band above the pill drags too. */
  insetTop?: boolean;
}) {
  if (narrow) {
    return (
      <div
        {...attrs}
        onPointerDown={onPointerDown}
        className="relative flex min-h-8 shrink-0 cursor-grab items-center justify-center touch-none"
      >
        {onToggle !== undefined && (
          <HandleIconButton
            attrs={{ "data-dock-minimize-all": "true" }}
            label={collapsed ? "Expand all panels" : "Minimize all panels"}
            title={collapsed ? "Expand all" : "Minimize all"}
            expanded={!collapsed}
            onActivate={onToggle}
            placement={{ position: "relative", width: "100%", height: "100%" }}
          >
            {collapsed ? <PlusIcon /> : <MinusIcon />}
          </HandleIconButton>
        )}
      </div>
    );
  }
  return (
    <div
      {...attrs}
      onPointerDown={onPointerDown}
      // The pill's band is the toggle, so it says what it does the way the
      // icon button used to.
      aria-label={
        onToggle === undefined
          ? undefined
          : collapsed
            ? "Expand all panels"
            : "Minimize all panels"
      }
      aria-expanded={onToggle === undefined ? undefined : !collapsed}
      className={`relative flex min-h-4 shrink-0 cursor-grab items-center justify-center touch-none select-none${
        insetTop ? " pt-2" : ""
      }`}
    >
      <GripPill width="3em" opacity={0.6} />
    </div>
  );
}
