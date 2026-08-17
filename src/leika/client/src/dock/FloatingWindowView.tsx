// Renders one free-floating window: a header handle (drags the whole window), a
// vertical stack of tab groups (the snap group), and edge resize grips (width
// on the sides, height on the bottom). Position is driven from layout state; the
// DockManager applies a transform during an active drag for smoothness.

import React from "react";
import { cn } from "@/lib/utils";
import { Card } from "../components/ui/card";
import { Separator } from "../components/ui/separator";
import { PeekHold, PeekHoldContext, useDock } from "./DockContext";
import { dragGesture } from "./gestures";
import { prefersReducedMotion } from "../utils/motion";
import {
  createFloatingStackResizeSession,
  floatingStackCellBudget,
} from "./floatingStackResize";
import { TabGroupFrame } from "./TabGroupFrame";
import {
  AUTO_HEIGHT_BOUNDARY_PAD_PX,
  clamp,
  FloatingWindow,
  GroupId,
  MAX_PANEL_WIDTH_PX,
  MIN_PANEL_WIDTH_PX,
  TabGroup,
  testIdForGroup,
} from "./types";

const MIN_WIDTH_PX = MIN_PANEL_WIDTH_PX;
const MAX_WIDTH_PX = MAX_PANEL_WIDTH_PX;
// A width-resize always leaves this much of the canvas visible.
const RESIZE_KEEP_CANVAS_PX = 100;
const MIN_HEIGHT_PX = 100;
// Minimum height for one group in a resizable snap-stack.
const MIN_STACK_CELL_PX = 60;
// Auto-height windows keep the same boundary breathing room as the original
// floating control panel (AUTO_HEIGHT_BOUNDARY_PAD_PX, shared with the
// anchoring rules). The budget applies to the WHOLE window -- headers, tab
// strips, dividers, and scroll bodies together.
const MULTI_GROUP_BODY_CAP_PX = 320;
const FALLBACK_BODY_CAP_PX = 600;
const OWNED_BODY_VIEWPORT_SELECTOR =
  '[data-dock-panel-scroll-body] > [data-slot="scroll-area-viewport"]';

/** How a `peekWhenCollapsed` window renders once it is collapsed AND the
 * pointer has left it: the card and everything in it gone, bar the panel's
 * `data-dock-peek` element.
 *
 * The peek element is dimmed rather than left at full strength -- alone on the
 * canvas it marks where the panel went rather than asking to be read -- and it
 * comes back up to full as the card arrives behind it.
 *
 * Faded, the card is click-through, so the canvas underneath stays reachable
 * and the peek element is the only target the window still offers. That is
 * what makes coming BACK a matter of finding the badge rather than waving at
 * the empty rectangle around it.
 *
 * Keyboard focus says the same thing in the keyboard's terms, and stays in CSS
 * because the pointer state cannot see it: tabbing to the gear must not leave
 * a focus ring on something invisible.
 *
 * Focus-VISIBLE rather than focus: closing a popout hands focus back to the
 * control that opened it, whether it was dismissed with a key or with a click
 * out on the canvas. Under plain `:focus-within` that restored focus held the
 * whole card open behind a pointer that had long since left -- the panel would
 * not fold until something else was clicked. Only a reader who is actually
 * driving from the keyboard needs to see where focus went. */
const FADED_CLASSES = [
  "pointer-events-none bg-transparent shadow-none ring-0",
  "[&_[data-dock-peek]]:pointer-events-auto [&_[data-dock-peek]]:opacity-60",
  "[&_[data-dock-peek-fade]]:opacity-0",
  "has-[:focus-visible]:pointer-events-auto has-[:focus-visible]:bg-card has-[:focus-visible]:shadow-md has-[:focus-visible]:ring-1",
  "has-[:focus-visible]:[&_[data-dock-peek]]:opacity-100 has-[:focus-visible]:[&_[data-dock-peek-fade]]:opacity-100",
].join(" ");

/** The fade itself, on the window whenever it can peek -- so the card fades
 * back IN as well as out, rather than snapping back the moment it is entered. */
const PEEK_TRANSITION_CLASSES = [
  "transition-[background-color,box-shadow] duration-200",
  "[&_[data-dock-peek]]:transition-opacity [&_[data-dock-peek]]:duration-200",
  "[&_[data-dock-peek-fade]]:transition-opacity [&_[data-dock-peek-fade]]:duration-200",
  "motion-reduce:transition-none [&_[data-dock-peek]]:motion-reduce:transition-none",
  "[&_[data-dock-peek-fade]]:motion-reduce:transition-none",
].join(" ");

// A deliberate one-second recovery window for slipping across the header
// edge; the existing 200ms visual fade starts only if the pointer stays away.
const PEEK_LEAVE_GRACE_MS = 1_000;

/** Return only the ScrollArea viewports owned by this floating window's
 * top-level groups. Nested DockAreas have their own group ids and must not be
 * double-counted as window bodies. */
function ownedBodyViewports(root: HTMLElement, groupIds: readonly GroupId[]) {
  const owners = new Set<GroupId>(groupIds);
  return Array.from(
    root.querySelectorAll<HTMLElement>(OWNED_BODY_VIEWPORT_SELECTOR),
  ).filter((viewport) => {
    const owner = viewport.closest<HTMLElement>("[data-dock-group]");
    return owner !== null && owners.has(owner.dataset.dockGroup as GroupId);
  });
}

export const FloatingWindowView = React.memo(function FloatingWindowView({
  win,
  zIndex,
  containerWidth,
  containerHeight,
  onResize,
  onResizeHeight,
  onSetStackWeights,
  onRestoreStackWeights,
  onFront,
}: {
  win: FloatingWindow;
  /** Paint order (front-order). Driven by z-index so raising a window never
   * reorders the DOM (which would eat in-flight clicks). */
  zIndex: number;
  /** Dock container width at the last resize reconciliation. Right-nearer
   * windows use it to render from their right inset, so native browser layout
   * keeps that inset immediately across a viewport resize. */
  containerWidth: number;
  /** Dock container height; auto-height windows cap their scrolling body to
   * it, so a tall panel scrolls internally instead of overflowing. */
  containerHeight: number;
  /** width plus, for left-edge resizes, the new x (so the right edge stays).
   * All handlers are windowId-first and STABLE, so this component can be
   * memoized (a re-render of the manager with an unchanged window skips it). */
  onResize: (windowId: string, width: number, x?: number) => void;
  onResizeHeight: (
    windowId: string,
    height: number | undefined,
    y?: number,
  ) => void;
  /** Merge per-group stack height weights (groupId -> weight). */
  onSetStackWeights: (
    windowId: string,
    weights: Record<GroupId, number>,
  ) => void;
  /** Restore only the stack groups captured at resize start. */
  onRestoreStackWeights: (
    windowId: string,
    groupIds: readonly GroupId[],
    weights: Readonly<Record<GroupId, number>> | undefined,
  ) => void;
  onFront: (windowId: string) => void;
}) {
  const dock = useDock();
  const multi = win.stack.length > 1;
  const testId = testIdForGroup(dock.panels, dock.groups[win.stack[0]]);
  const paperRef = React.useRef<HTMLDivElement>(null);
  const stackRef = React.useRef<HTMLDivElement>(null);
  // A fully-minimized window shrinks to its handle(s); it ignores any fixed
  // height and offers no vertical resize (there's nothing to resize).
  const collapsed = win.stack.every(
    (id) => dock.groups[id]?.collapsed === true,
  );
  // Every panel in the stack has to want this: one that does not would be
  // faded out along with the window it happens to share.
  const peek =
    collapsed &&
    win.stack.every((id) => {
      const group = dock.groups[id];
      return (
        group !== undefined &&
        dock.panels[group.activeId]?.peekWhenCollapsed === true
      );
    });
  // Pointer state rather than `:hover`, because the two are not the same thing
  // here. Faded, the card is click-through, so a pointer resting over it is
  // NOT hovering it -- under `:hover` the card would vanish from under the
  // cursor the instant a click collapsed it, taking the second click of a
  // double-click with it. Entering is still `:hover`'s job in effect (the peek
  // element is the only thing left to enter); leaving is what this tracks.
  const [pointerInside, setPointerInside] = React.useState(false);
  const [leaveGraceActive, setLeaveGraceActive] = React.useState(false);
  const leaveGraceTimeoutRef = React.useRef<number | null>(null);
  const clearLeaveGraceTimer = React.useCallback(() => {
    if (leaveGraceTimeoutRef.current === null) return;
    window.clearTimeout(leaveGraceTimeoutRef.current);
    leaveGraceTimeoutRef.current = null;
  }, []);
  const cancelLeaveGrace = React.useCallback(() => {
    clearLeaveGraceTimer();
    setLeaveGraceActive(false);
  }, [clearLeaveGraceTimer]);
  const startLeaveGrace = React.useCallback(() => {
    clearLeaveGraceTimer();
    setLeaveGraceActive(true);
    leaveGraceTimeoutRef.current = window.setTimeout(() => {
      leaveGraceTimeoutRef.current = null;
      setLeaveGraceActive(false);
    }, PEEK_LEAVE_GRACE_MS);
  }, [clearLeaveGraceTimer]);
  React.useEffect(() => clearLeaveGraceTimer, [clearLeaveGraceTimer]);
  // Anything the panel put outside itself and still counts as itself -- a
  // popout hung off its header -- holds the window here while it is up. See
  // `usePeekHold`.
  const [peekHolds, setPeekHolds] = React.useState(0);
  const peekRef = React.useRef(peek);
  peekRef.current = peek;
  const deferredPeekReleasesRef = React.useRef(new Set<() => void>());
  const deferredPeekReleaseArmedRef = React.useRef(false);
  const holdPeek = React.useCallback<PeekHold>(() => {
    setPeekHolds((held) => held + 1);
    let held = true;
    const releaseNow = () => {
      if (!held) return;
      held = false;
      deferredPeekReleasesRef.current.delete(releaseNow);
      setPeekHolds((count) => Math.max(0, count - 1));
    };
    return (release = "immediate") => {
      if (!held) return;
      if (release === "after-pointer-return" && peekRef.current) {
        deferredPeekReleasesRef.current.add(releaseNow);
        return;
      }
      releaseNow();
    };
  }, []);
  React.useEffect(() => {
    if (peek) return;
    cancelLeaveGrace();
    deferredPeekReleaseArmedRef.current = false;
    for (const release of Array.from(deferredPeekReleasesRef.current)) {
      release();
    }
  }, [cancelLeaveGrace, peek]);
  const markPhysicalPointerReturn = React.useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      // React events from an owned portal bubble through this component too.
      // Only a target in the card's real DOM subtree means the pointer has
      // actually returned to the collapsed header.
      if (
        !(event.target instanceof Node) ||
        !event.currentTarget.contains(event.target)
      ) {
        return;
      }
      cancelLeaveGrace();
      setPointerInside(true);
      if (deferredPeekReleasesRef.current.size > 0) {
        deferredPeekReleaseArmedRef.current = true;
      }
    },
    [cancelLeaveGrace],
  );
  const markPointerOutside = React.useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (
        !(event.target instanceof Node) ||
        !event.currentTarget.contains(event.target)
      ) {
        return;
      }
      setPointerInside(false);
      if (peekRef.current) {
        startLeaveGrace();
      } else {
        cancelLeaveGrace();
      }
      if (!deferredPeekReleaseArmedRef.current) {
        return;
      }
      deferredPeekReleaseArmedRef.current = false;
      for (const release of Array.from(deferredPeekReleasesRef.current)) {
        release();
      }
    },
    [cancelLeaveGrace, startLeaveGrace],
  );
  const faded = peek && !pointerInside && !leaveGraceActive && peekHolds === 0;
  const fixedHeight = win.height !== undefined && !collapsed;
  const [autoBodyMaxHeight, setAutoBodyMaxHeight] = React.useState<
    number | undefined
  >();
  // Re-measure when the set/type of visible bodies changes. A tab switch can
  // replace a regular scroll body with a full-bleed panel without changing the
  // window itself, while minimizing one cell changes the amount of chrome.
  const autoBodyKey = win.stack
    .map((id) => {
      const group = dock.groups[id];
      const panel =
        group === undefined ? undefined : dock.panels[group.activeId];
      return `${id}:${group?.activeId ?? ""}:${group?.collapsed === true ? 1 : 0}:${
        panel?.fullBleed === true ? 1 : 0
      }`;
    })
    .join("|");
  // A pinned height is capped to the container so the window stays usable when
  // the browser shrinks below the saved height (the groups inside scroll).
  // Deliberately independent of win.y: moving a window must never change its
  // size, so a pinned-height window dragged low simply overhangs the bottom
  // edge -- exactly like an auto-height window does. Floored at MIN_HEIGHT_PX
  // for tiny containers.
  const renderedHeight =
    win.height !== undefined && containerHeight > 0
      ? Math.min(win.height, Math.max(MIN_HEIGHT_PX, containerHeight - 8))
      : win.height;

  // `maxContentHeight` is a BODY cap, but staying inside the viewport is a
  // WHOLE-WINDOW constraint. Measure the live non-scroll chrome instead of
  // subtracting a guessed header height: that keeps unmergeable headers,
  // ordinary tab strips, nested stacks, and future visual changes correct.
  // For a stack, every visible scroll body receives an equal share, capped at
  // 320 px per group.
  React.useLayoutEffect(() => {
    if (fixedHeight || collapsed || containerHeight <= 0) return;
    const paper = paperRef.current;
    if (paper === null) return;
    const measure = () => {
      const viewports = ownedBodyViewports(paper, win.stack).filter(
        (viewport) => viewport.clientHeight > 0,
      );
      if (viewports.length === 0) return;
      const renderedBodyHeight = viewports.reduce(
        (sum, viewport) => sum + viewport.clientHeight,
        0,
      );
      const chromeHeight = Math.max(0, paper.offsetHeight - renderedBodyHeight);
      const wholeWindowBudget = Math.max(
        0,
        containerHeight - 2 * AUTO_HEIGHT_BOUNDARY_PAD_PX,
      );
      const sharedBodyBudget = Math.max(0, wholeWindowBudget - chromeHeight);
      const next = multi
        ? Math.min(MULTI_GROUP_BODY_CAP_PX, sharedBodyBudget / viewports.length)
        : sharedBodyBudget;
      setAutoBodyMaxHeight((previous) =>
        previous === undefined || Math.abs(previous - next) > 0.5
          ? next
          : previous,
      );
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(paper);
    return () => observer.disconnect();
  }, [
    autoBodyKey,
    collapsed,
    containerHeight,
    fixedHeight,
    multi,
    win.stack,
    win.width,
  ]);

  // Match DockManager's nearer-edge resize anchoring in the rendered CSS, not
  // only after its ResizeObserver callback. Playwright (and real browser code)
  // can inspect layout in the small interval after the viewport has changed
  // but before ResizeObserver delivery. A right inset responds as part of the
  // browser's own layout pass, keeping a top-right control panel on-screen in
  // that interval. Once the observer reconciles `win.x`, the derived inset is
  // unchanged, so there is no intermediate jump or persistence drift.
  const anchorRight =
    containerWidth > 0 && win.x + win.width / 2 > containerWidth / 2;

  const horizontalPosition = anchorRight
    ? { left: undefined, right: containerWidth - win.x - win.width }
    : { left: win.x, right: undefined };

  // Animate collapse/expand by FLIP-ing the window height: each render notes
  // the Paper's resting height; when the collapsed state flips we replay the
  // previous height and transition to the new one. ONLY for windows with a
  // pinned height (full-bleed / user-resized), whose body can't be measured by
  // a <Collapse>: auto-height windows let the body's own <Collapse> drive the
  // animation -- FLIP-ing those would measure the target before the Collapse
  // opens and pin the Paper at the still-collapsed height while the expanding
  // content spills out. Resizes update the baseline but don't animate.
  const prevHeightRef = React.useRef<number | null>(null);
  const prevCollapsedRef = React.useRef(collapsed);
  // Cancels the in-flight animation (clears inline styles + listener), if any.
  const flipCancelRef = React.useRef<(() => void) | null>(null);
  React.useLayoutEffect(() => {
    const p = paperRef.current;
    if (p === null) return;
    const flipped = prevCollapsedRef.current !== collapsed;
    prevCollapsedRef.current = collapsed;
    if (win.height === undefined) {
      flipCancelRef.current?.();
      prevHeightRef.current = null;
      return;
    }
    if (!flipped) {
      // Keep the resting baseline fresh (resizes, content changes) -- but not
      // while an animation is in flight, when the inline height would be
      // mistaken for the resting height. Expanded, the resting height IS the
      // pinned win.height (no layout read needed); collapsed (auto-sized to the
      // handles) it has to be measured.
      if (flipCancelRef.current === null)
        prevHeightRef.current = collapsed
          ? p.offsetHeight
          : (renderedHeight ?? null);
      return;
    }
    // If a previous flip is still animating, start the new transition from the
    // current ON-SCREEN height (so a mid-animation re-toggle reverses smoothly)
    // and cancel it so the resting target can be measured.
    const interruptedAt =
      flipCancelRef.current !== null ? p.getBoundingClientRect().height : null;
    flipCancelRef.current?.();
    const target = p.offsetHeight;
    const start = interruptedAt ?? prevHeightRef.current;
    prevHeightRef.current = target;
    if (start === null || Math.abs(start - target) < 1) return;
    if (prefersReducedMotion()) return;
    // ONE WRITER PER STYLE PROPERTY: React owns `height` (it renders the
    // pinned renderedHeight), so the animation drives min-height/max-height
    // -- properties React never writes on the Paper. Pinning both forces the
    // box through the transition in either direction, and clearing them on
    // cancel hands control back cleanly BY CONSTRUCTION: there is no React
    // style-cache entry for them to disagree with. (Animating `height` here
    // and "handing it back" by clearing the inline value left the window at
    // 0px: React's cache still held the old height, so it never re-wrote it.)
    p.style.transition = "none";
    p.style.minHeight = `${start}px`;
    p.style.maxHeight = `${start}px`;
    void p.offsetHeight; // force a reflow so the start height takes effect
    p.style.transition = "min-height 180ms ease, max-height 180ms ease";
    p.style.minHeight = `${target}px`;
    p.style.maxHeight = `${target}px`;
    const cancel = () => {
      flipCancelRef.current = null;
      p.style.transition = "";
      p.style.minHeight = "";
      p.style.maxHeight = "";
      p.removeEventListener("transitionend", onEnd);
    };
    const onEnd = (e: TransitionEvent) => {
      // Child transitions bubble; only our own animation ends the FLIP (both
      // pinned properties finish together -- listen for one of them).
      if (e.target === p && e.propertyName === "max-height") cancel();
    };
    flipCancelRef.current = cancel;
    p.addEventListener("transitionend", onEnd);
  });
  // Clear in-flight animation styles/listener if the window unmounts mid-flip.
  React.useEffect(() => () => flipCancelRef.current?.(), []);

  // Cancel an in-flight grip gesture if this window unmounts mid-resize (e.g.
  // another client docks it away), so its listeners can't fire afterwards. One
  // ref serves all grips: only one resize gesture may be active per window (a
  // second finger on another grip is ignored while one is running).
  const activeGrip = React.useRef<(() => void) | null>(null);
  React.useEffect(() => () => activeGrip.current?.(), []);

  // Container-relative width cap: a resize
  // always leaves a sliver of canvas visible (it may never consume the whole
  // container), on top of the absolute MAX_WIDTH_PX.
  const maxResizeWidth = () => {
    const containerW = paperRef.current?.parentElement?.clientWidth ?? Infinity;
    return Math.max(
      MIN_WIDTH_PX,
      Math.min(MAX_WIDTH_PX, containerW - RESIZE_KEEP_CANVAS_PX),
    );
  };

  const widthResizeHandler =
    (side: "left" | "right") => (event: React.PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return;
      if (activeGrip.current !== null) return;
      event.stopPropagation();
      const startX = event.clientX;
      const startWidth = win.width;
      // Right edge in parent coords; held fixed when resizing from the left.
      const startRight = win.x + win.width;
      const maxW = maxResizeWidth();

      let pending = startWidth;
      let pendingX: number | undefined = undefined;
      activeGrip.current = dragGesture({
        grip: event.currentTarget,
        pointerId: event.pointerId,
        update: (e) => {
          const delta = e.clientX - startX;
          const raw =
            side === "right" ? startWidth + delta : startWidth - delta;
          pending = clamp(raw, MIN_WIDTH_PX, maxW);
          // Left-edge resize: keep the right edge fixed by moving x.
          pendingX = side === "left" ? startRight - pending : undefined;
        },
        flush: () => onResize(win.id, pending, pendingX),
        coordinator: dock.gestureCoordinator,
        onEnd: (cancelled) => {
          activeGrip.current = null;
          // Cancel (Escape) reverts the per-frame resizes to the start size.
          if (cancelled)
            onResize(
              win.id,
              startWidth,
              side === "left" ? startRight - startWidth : undefined,
            );
        },
      });
    };

  // Largest height the panel may take: the smaller of the container and the
  // natural content height (so it can't be dragged taller than its contents).
  // scrollHeight on each scroll viewport gives its full uncapped content; the
  // rest of the paper (strips, headers, dividers, borders) is chrome.
  const measureMaxHeight = () => {
    const paper = paperRef.current;
    const containerMax = (paper?.parentElement?.clientHeight ?? 2000) - 16;
    if (paper === null) return containerMax;
    let scrollSum = 0;
    let clientSum = 0;
    ownedBodyViewports(paper, win.stack).forEach((v) => {
      scrollSum += (v as HTMLElement).scrollHeight;
      clientSum += (v as HTMLElement).clientHeight;
    });
    const contentMax = paper.offsetHeight - clientSum + scrollSum;
    return clamp(contentMax, MIN_HEIGHT_PX, containerMax);
  };

  // Start-of-gesture math shared by every vertical resize: top-side grips
  // hold the BOTTOM edge fixed by moving y with the height (the vertical
  // analog of a left-edge width resize), with the height additionally capped
  // at the start bottom so the top edge can't leave the container.
  const vResizeStart = (vside: "top" | "bottom") => {
    const startHeight = paperRef.current?.offsetHeight ?? win.height ?? 200;
    const startBottom = win.y + startHeight;
    const maxHeight =
      vside === "top"
        ? Math.min(measureMaxHeight(), startBottom)
        : measureMaxHeight();
    return {
      startHeight,
      heightFrom: (dy: number) =>
        clamp(
          vside === "top" ? startHeight - dy : startHeight + dy,
          MIN_HEIGHT_PX,
          maxHeight,
        ),
      yFor: (h: number) => (vside === "top" ? startBottom - h : undefined),
    };
  };

  const heightResizeHandler =
    (vside: "top" | "bottom") =>
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return;
      if (activeGrip.current !== null) return;
      event.stopPropagation();
      const startY = event.clientY;
      const startExplicitHeight = win.height;
      const startWindowY = win.y;
      const { startHeight, heightFrom, yFor } = vResizeStart(vside);

      let pending = startHeight;
      activeGrip.current = dragGesture({
        grip: event.currentTarget,
        pointerId: event.pointerId,
        update: (e) => {
          pending = heightFrom(e.clientY - startY);
        },
        flush: () => onResizeHeight(win.id, pending, yFor(pending)),
        coordinator: dock.gestureCoordinator,
        onEnd: (cancelled) => {
          activeGrip.current = null;
          if (cancelled) {
            // Restore persisted state, not the rendered measurement used for
            // drag math: an auto-height window must remain auto-height.
            onResizeHeight(
              win.id,
              startExplicitHeight,
              vside === "top" ? startWindowY : undefined,
            );
          }
        },
      });
    };

  // Corner grips: resize width AND height together. The grabbed corner moves;
  // the opposite edges stay fixed (left grab moves x, top grab moves y).
  const cornerResizeHandler =
    (side: "left" | "right", vside: "top" | "bottom" = "bottom") =>
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return;
      if (activeGrip.current !== null) return;
      event.stopPropagation();
      const startX = event.clientX;
      const startY = event.clientY;
      const startWidth = win.width;
      const startRight = win.x + win.width;
      const startExplicitHeight = win.height;
      const startWindowY = win.y;
      const { startHeight, heightFrom, yFor } = vResizeStart(vside);
      const maxW = maxResizeWidth();

      let pendingW = startWidth;
      let pendingX: number | undefined = undefined;
      let pendingH = startHeight;
      activeGrip.current = dragGesture({
        grip: event.currentTarget,
        pointerId: event.pointerId,
        update: (e) => {
          const dx = e.clientX - startX;
          const raw = side === "right" ? startWidth + dx : startWidth - dx;
          pendingW = clamp(raw, MIN_WIDTH_PX, maxW);
          pendingX = side === "left" ? startRight - pendingW : undefined;
          pendingH = heightFrom(e.clientY - startY);
        },
        flush: () => {
          onResize(win.id, pendingW, pendingX);
          onResizeHeight(win.id, pendingH, yFor(pendingH));
        },
        coordinator: dock.gestureCoordinator,
        onEnd: (cancelled) => {
          activeGrip.current = null;
          if (cancelled) {
            onResize(win.id, startWidth, side === "left" ? win.x : undefined);
            onResizeHeight(
              win.id,
              startExplicitHeight,
              vside === "top" ? startWindowY : undefined,
            );
          }
        },
      });
    };

  return (
    <PeekHoldContext.Provider value={holdPeek}>
      <Card
        ref={paperRef}
        data-floating-window={win.id}
        data-testid={testId}
        data-dock-side="none"
        data-dock-peeking={faded ? "true" : undefined}
        // Floating windows hover over the viewport, so they get a drop shadow to
        // lift them off it. Docked and split cards stay flat -- they tile the
        // surface rather than sitting on top of it.
        // `py-0`: the window's vertical inset is carried by the handles at its
        // top and bottom instead, so the whole band around them drags (see
        // CARD_INSET_TOP in cardInset).
        className={cn(
          "box-border py-0 shadow-md",
          peek && PEEK_TRANSITION_CLASSES,
          faded && FADED_CLASSES,
        )}
        onPointerDownCapture={(event) => {
          onFront(win.id);
          // A press inside the card proves the pointer is inside it, whether
          // or not an enter ever fired (see onPointerMove).
          markPhysicalPointerReturn(event);
        }}
        // Enter fires for the peek element too: entering a descendant from
        // outside is entering the card. That is the way back in once the card
        // itself has stopped taking the pointer.
        onPointerEnter={markPhysicalPointerReturn}
        // A window BORN under the cursor -- dragged out of the dock, the
        // pointer captured to it from its first frame -- may never receive
        // that enter: boundary events chase crossings, and this pointer never
        // crossed in. Left untracked, collapsing the fresh window folds it
        // down to its peek badge with the cursor still on the header. Any
        // traffic inside the card says what the missing enter would have (a
        // same-value set is a no-op re-render-wise).
        onPointerMove={markPhysicalPointerReturn}
        onPointerLeave={markPointerOutside}
        style={{
          position: "absolute",
          ...horizontalPosition,
          top: win.y,
          width: win.width,
          height: collapsed ? undefined : renderedHeight,
          zIndex,
          overflow: "visible",
          // When height is fixed, lay the stack out as a flex column so groups
          // share the height and scroll internally.
          ...(fixedHeight
            ? { display: "flex", flexDirection: "column" as const }
            : {}),
        }}
      >
        {/* Edge resize grips. */}
        <ResizeGrip
          edge="left"
          testId={testId && `${testId}-resize-left`}
          onPointerDown={widthResizeHandler("left")}
        />
        <ResizeGrip
          edge="right"
          testId={testId && `${testId}-resize-right`}
          onPointerDown={widthResizeHandler("right")}
        />
        {/* No vertical / corner resize when minimized -- nothing to resize. */}
        {!collapsed && (
          <>
            <ResizeGrip
              edge="bottom"
              onPointerDown={heightResizeHandler("bottom")}
            />
            <ResizeGrip edge="top" onPointerDown={heightResizeHandler("top")} />
            <ResizeGrip
              edge="bottom-left"
              onPointerDown={cornerResizeHandler("left")}
            />
            <ResizeGrip
              edge="bottom-right"
              onPointerDown={cornerResizeHandler("right")}
            />
            <ResizeGrip
              edge="top-left"
              onPointerDown={cornerResizeHandler("left", "top")}
            />
            <ResizeGrip
              edge="top-right"
              onPointerDown={cornerResizeHandler("right", "top")}
            />
          </>
        )}

        <div
          style={{
            overflow: "hidden",
            ...(fixedHeight
              ? {
                  flexGrow: 1,
                  minHeight: 0,
                  display: "flex",
                  flexDirection: "column" as const,
                }
              : {}),
          }}
        >
          {/* No window header: every member's tab strip is a handle on the
        whole window (a stack moves as one, from any of its strips), and a
        member is pulled OUT by its tab's grip. */}
          <div
            ref={stackRef}
            style={
              fixedHeight
                ? {
                    flexGrow: 1,
                    minHeight: 0,
                    display: "flex",
                    flexDirection: "column",
                  }
                : {}
            }
          >
            {win.stack.map((groupId, index) => {
              const group = dock.groups[groupId];
              if (group === undefined) return null;
              const collapsedCell = group.collapsed === true;
              const weight = win.stackWeights?.[groupId] ?? 1;
              const groupNode = (
                <TabGroupFrame
                  group={group}
                  // Fixed-height windows: groups fill and share the height (the
                  // wrapper carries the per-group weight). Auto-height: size to
                  // content, capped to the dock container's height (minus a
                  // margin) -- falling back to a
                  // fixed cap before the first container measure.
                  fill={fixedHeight}
                  maxContentHeight={
                    autoBodyMaxHeight ??
                    (multi
                      ? MULTI_GROUP_BODY_CAP_PX
                      : containerHeight > 0
                        ? Math.max(
                            0,
                            containerHeight - 2 * AUTO_HEIGHT_BOUNDARY_PAD_PX,
                          )
                        : FALLBACK_BODY_CAP_PX)
                  }
                  // The window's vertical inset belongs to whatever sits against
                  // each edge of the card: the stack's first and last groups,
                  // except at the top of a multi-group window, where the window
                  // header is already there to take it.
                  insetTop={index === 0}
                  insetBottom={index === win.stack.length - 1}
                  stripDragsGroup
                />
              );
              return (
                <React.Fragment key={groupId}>
                  {index > 0 && (
                    // Draggable: redistribute height between the stacked groups
                    // (same cascade as docked column splits). On an auto-height
                    // window the first effective resize pins the current height.
                    <FloatingStackDivider
                      stackRef={stackRef}
                      dividerIndex={index - 1}
                      stack={win.stack}
                      stackWeights={win.stackWeights}
                      groups={dock.groups}
                      weightOf={(g) => win.stackWeights?.[g] ?? 1}
                      onSetWeights={(weights) =>
                        onSetStackWeights(win.id, weights)
                      }
                      onRestoreWeights={(groupIds, weights) =>
                        onRestoreStackWeights(win.id, groupIds, weights)
                      }
                      isFixed={fixedHeight}
                      pinHeight={() => {
                        const p = paperRef.current;
                        if (p) onResizeHeight(win.id, p.offsetHeight);
                      }}
                      restoreAutoHeight={() =>
                        onResizeHeight(win.id, undefined)
                      }
                    />
                  )}
                  {fixedHeight ? (
                    <div
                      style={{
                        flexGrow: collapsedCell ? 0 : weight,
                        flexShrink: collapsedCell ? 0 : 1,
                        flexBasis: collapsedCell ? "auto" : 0,
                        minHeight: 0,
                        display: "flex",
                        flexDirection: "column",
                      }}
                    >
                      {groupNode}
                    </div>
                  ) : (
                    groupNode
                  )}
                </React.Fragment>
              );
            })}
          </div>
        </div>
      </Card>
    </PeekHoldContext.Provider>
  );
});

/** Draggable divider between two groups in a floating snap-stack. An
 * auto-height stack is pinned only after its first effective resize.
 * Redistributes height between the stacked groups using the same cascade as
 * docked column splits, writing per-group weights (by id). */
function FloatingStackDivider({
  stackRef,
  dividerIndex,
  stack,
  stackWeights,
  groups,
  weightOf,
  onSetWeights,
  onRestoreWeights,
  isFixed,
  pinHeight,
  restoreAutoHeight,
}: {
  stackRef: React.RefObject<HTMLDivElement | null>;
  dividerIndex: number;
  stack: GroupId[];
  stackWeights: Readonly<Record<GroupId, number>> | undefined;
  groups: Record<GroupId, TabGroup>;
  weightOf: (g: GroupId) => number;
  onSetWeights: (weights: Record<GroupId, number>) => void;
  onRestoreWeights: (
    groupIds: readonly GroupId[],
    weights: Readonly<Record<GroupId, number>> | undefined,
  ) => void;
  /** Whether the window already has a fixed height (so weights apply directly).
   * If false, the first effective resize pins the current rendered height. */
  isFixed: boolean;
  pinHeight: () => void;
  restoreAutoHeight: () => void;
}) {
  const { gestureCoordinator, setResizing } = useDock();
  // Cancel the in-flight gesture if the divider unmounts mid-drag (the stack
  // can be restructured by another client), so the window listeners can't fire
  // after unmount and the shared `resizing` flag can't stick true.
  const activeDrag = React.useRef<(() => void) | null>(null);
  React.useEffect(() => () => activeDrag.current?.(), []);
  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    if (activeDrag.current !== null) return; // one drag per divider
    event.stopPropagation();
    const container = stackRef.current;
    if (container === null) return;
    const containerPx = container.getBoundingClientRect().height;
    const collapsed = stack.map(
      (groupId) => groups[groupId]?.collapsed === true,
    );
    const groupElements = new Map<GroupId, HTMLElement>();
    const stackIds = new Set(stack);
    container
      .querySelectorAll<HTMLElement>("[data-dock-group]")
      .forEach((element) => {
        const groupId = element.dataset.dockGroup;
        if (groupId !== undefined && stackIds.has(groupId)) {
          groupElements.set(groupId, element);
        }
      });
    const dividerHeights = Array.from(container.children)
      .filter((element) => element.hasAttribute("data-floating-divider"))
      .map((element) => element.getBoundingClientRect().height);
    const collapsedCellHeights = stack.flatMap((groupId, index) =>
      collapsed[index]
        ? [groupElements.get(groupId)?.getBoundingClientRect().height ?? 0]
        : [],
    );
    const cellBudget = floatingStackCellBudget(
      containerPx,
      dividerHeights,
      collapsedCellHeights,
    );
    const resizeSession = createFloatingStackResizeSession({
      stack,
      // An auto-height stack has no weights on screen yet. Preserve its actual
      // rendered proportions when the first effective drag pins the height.
      weights: stack.map((groupId, index) =>
        !isFixed && !collapsed[index]
          ? (groupElements.get(groupId)?.getBoundingClientRect().height ??
            weightOf(groupId))
          : weightOf(groupId),
      ),
      stackWeights,
      collapsed,
      containerPx: cellBudget,
      dividerIndex,
      minCell: MIN_STACK_CELL_PX,
      fixedHeight: isFixed,
    });
    const start = event.clientY;
    let latest = start;
    activeDrag.current = dragGesture({
      grip: event.currentTarget,
      pointerId: event.pointerId,
      update: (e) => {
        latest = e.clientY;
      },
      flush: () => {
        const update = resizeSession.applyDelta(latest - start);
        if (update === null) return;
        if (update.pinAutoHeight) pinHeight();
        onSetWeights(update.weights);
      },
      coordinator: gestureCoordinator,
      onStart: () => setResizing(true),
      onEnd: (cancelled) => {
        activeDrag.current = null;
        setResizing(false);
        if (!cancelled) return;
        const rollback = resizeSession.rollback();
        onRestoreWeights(rollback.groupIds, rollback.stackWeights);
        if (rollback.restoreAutoHeight) restoreAutoHeight();
      },
    });
  };
  return (
    <div
      data-floating-divider={dividerIndex}
      onPointerDown={onPointerDown}
      style={{
        flexShrink: 0,
        height: "7px",
        cursor: "ns-resize",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        touchAction: "none",
        zIndex: 2,
      }}
    >
      <Separator />
    </div>
  );
}

function ResizeGrip({
  edge,
  onPointerDown,
  testId,
}: {
  edge:
    | "left"
    | "right"
    | "top"
    | "bottom"
    | "top-left"
    | "top-right"
    | "bottom-left"
    | "bottom-right";
  onPointerDown: (event: React.PointerEvent<HTMLDivElement>) => void;
  /** Set by windows whose panel declares a `testId`. */
  testId?: string;
}) {
  // Corners win over edges (higher z) so the diagonal cursor + combined resize
  // take priority where they overlap.
  const corner = edge.includes("-");
  const position: React.CSSProperties = corner
    ? {
        [edge.startsWith("top") ? "top" : "bottom"]: "-3px",
        [edge.endsWith("left") ? "left" : "right"]: "-3px",
        width: "14px",
        height: "14px",
      }
    : edge === "bottom" || edge === "top"
      ? { left: 0, right: 0, [edge]: "-3px", height: "8px" }
      : { top: 0, bottom: 0, [edge]: "-3px", width: "8px" };
  const cursor = corner
    ? edge === "bottom-left" || edge === "top-right"
      ? "nesw-resize"
      : "nwse-resize"
    : edge === "bottom" || edge === "top"
      ? "ns-resize"
      : "ew-resize";
  return (
    <div
      data-dock-resize={edge}
      data-testid={testId}
      onPointerDown={onPointerDown}
      style={{
        position: "absolute",
        ...position,
        cursor,
        zIndex: corner ? 13 : 12,
        touchAction: "none",
      }}
    />
  );
}
