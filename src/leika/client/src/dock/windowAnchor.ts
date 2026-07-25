// Pure geometry for the DockManager's DOM layer: where a floating window's
// corner lands when the container resizes, and how to read a CSS transform's
// translation back off an element.
//
// Both were inline in DockManager, where the surrounding code is DOM- and
// React-bound and the rules could only be checked by hand. They are ordinary
// arithmetic, so they live here and are covered by windowAnchor.test.ts.

import { clamp } from "./types";

/** Keep at least this much of a floating window's top-left corner on-screen so
 * its handle stays reachable (panels may otherwise overflow off-screen). */
export const KEEP_VISIBLE_PX = 40;

/** Clamp a floating window's top-left corner so the handle stays reachable. The
 * corner stays within the container (no off-top/left), but the window body may
 * extend past the right/bottom edges. */
export function clampCorner(
  x: number,
  y: number,
  containerW: number,
  containerH: number,
): [number, number] {
  return [
    clamp(x, 0, containerW - KEEP_VISIBLE_PX),
    clamp(y, 0, containerH - KEEP_VISIBLE_PX),
  ];
}

/** Where a floating window's corner goes when the dock container resizes from
 * `prev` to `next`.
 *
 * Each axis anchors to the NEARER container edge: a window whose center sits in
 * the right/bottom half keeps its distance to that edge, so e.g. a top-right
 * control panel stays in the top-right corner when the browser window grows.
 * A window larger than the container on an axis doesn't anchor on it (there is
 * no meaningful "nearer edge" -- it spans both).
 *
 * A container SHRINK additionally pulls windows fully on-screen when they fit:
 * overhang from a drag is the user's choice, but losing the far edge -- and its
 * minimize/resize controls -- to a browser resize isn't. Per axis and on shrink
 * only, so a width-only resize can't yank a bottom-overhanging window upward
 * and a GROW (which loses nothing) can't cancel deliberate overhang.
 *
 * `prev === null` is the observer's initial fire: there is no delta to apply,
 * and second-guessing the caller's deliberate placement would be wrong, so only
 * the corner clamp runs.
 *
 * `win.height` is the window's RENDERED height (what the user sees), or 0 when
 * it has no DOM yet -- an unknown height skips vertical anchoring and pulling
 * rather than guessing.
 */
export function anchorFloatingWindow(
  win: { x: number; y: number; width: number; height: number },
  prev: { width: number; height: number } | null,
  next: { width: number; height: number },
): [number, number] {
  let x = win.x;
  let y = win.y;
  const deltaW = prev === null ? 0 : next.width - prev.width;
  const deltaH = prev === null ? 0 : next.height - prev.height;
  if (prev !== null && (deltaW !== 0 || deltaH !== 0)) {
    if (win.width <= prev.width && win.x + win.width / 2 > prev.width / 2) {
      x += deltaW;
    }
    if (win.height <= prev.height && win.y + win.height / 2 > prev.height / 2) {
      y += deltaH;
    }
    if (deltaW < 0) x = Math.min(x, Math.max(0, next.width - win.width));
    if (deltaH < 0 && win.height > 0) {
      y = Math.min(y, Math.max(0, next.height - win.height));
    }
  }
  return clampCorner(x, y, next.width, next.height);
}

/** The translation component of a computed CSS `transform`, as [tx, ty].
 *
 * getComputedStyle resolves every transform to a matrix: `matrix(a,b,c,d,tx,ty)`
 * for 2D and `matrix3d(...)` (16 values, translation at 13/14) for 3D. Anything
 * else -- "none", "", or an unparseable value -- reads as no translation. */
export function translationOf(transform: string): [number, number] {
  if (transform === "none" || transform === "") return [0, 0];
  const open = transform.indexOf("(");
  const close = transform.lastIndexOf(")");
  if (open === -1 || close < open) return [0, 0];
  const values = transform
    .slice(open + 1, close)
    .split(",")
    .map((value) => parseFloat(value));
  const pair =
    values.length === 6
      ? [values[4], values[5]]
      : values.length === 16
        ? [values[12], values[13]]
        : null;
  if (pair === null || !Number.isFinite(pair[0]) || !Number.isFinite(pair[1])) {
    return [0, 0];
  }
  return [pair[0], pair[1]];
}
