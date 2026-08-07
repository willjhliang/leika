import React from "react";

import { DOCUMENT_ID_PREFIX } from "../markdown";
import { renderMarkdown } from "./markdownDocument";

/** The part of the document a `#fragment` names, as it was written.
 *
 * A link's target is percent-encoded where a heading's text needed it -- a
 * link to "## Café" is written `#caf%C3%A9` -- and the id it lands on is the
 * text itself. Anything that is not encoding is left as it stands, because no
 * document fails: a malformed escape is a fragment that matches nothing, not
 * an error thrown out of a click.
 */
function fragmentOf(href: string): string {
  const raw = href.slice(1);
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

/** How long the carry from a link to its heading takes.
 *
 * A fixed beat: long enough to read as motion through the document rather
 * than a cut, short enough that the reader is never waiting on it. This is
 * why the scroll is animated by hand at all -- the browser's own smooth
 * scroll has no duration to set, and the one it picks grows with distance,
 * so a contents link pointing deep into a README turns into a glide.
 */
const SCROLL_DURATION_MS = 200;

/** The box the document actually scrolls in: dialog frame or panel body. */
function scrollFrameOf(element: HTMLElement): HTMLElement | null {
  for (
    let node = element.parentElement;
    node !== null;
    node = node.parentElement
  ) {
    if (node.scrollHeight > node.clientHeight) {
      const { overflowY } = getComputedStyle(node);
      if (overflowY === "auto" || overflowY === "scroll") return node;
    }
  }
  return null;
}

// The scroll in flight, so a second click supersedes it rather than fighting
// it frame by frame. One is enough: only one document is ever being carried.
let cancelCarry: (() => void) | null = null;

/** Scroll `frame` until `target` sits at its top, in one short eased move. */
function carryTo(frame: HTMLElement, target: HTMLElement): void {
  cancelCarry?.();
  const from = frame.scrollTop;
  const offset =
    target.getBoundingClientRect().top - frame.getBoundingClientRect().top;
  const to = Math.max(
    0,
    Math.min(from + offset, frame.scrollHeight - frame.clientHeight),
  );
  const started = performance.now();
  let handle = requestAnimationFrame(function step(now: number) {
    const at = Math.min(1, (now - started) / SCROLL_DURATION_MS);
    // Ease-out: the move spends its speed early and lands softly, which is
    // what makes a fast scroll read as travel rather than as a jolt.
    frame.scrollTop = from + (to - from) * (1 - (1 - at) ** 3);
    if (at < 1) handle = requestAnimationFrame(step);
  });
  cancelCarry = () => cancelAnimationFrame(handle);
}

/**
 * Follow a link from one part of a document to another.
 *
 * A contents list at the top of a README is links into the same file, and the
 * browser's own answer to one is to put the fragment in the address bar and
 * jump. Neither half of that suits a document being *previewed*: the address
 * is the app's, and a jump loses the reader the thread between where they were
 * and where the link took them. So the click is answered here instead -- the
 * document scrolls itself, and nothing outside it moves.
 *
 * The lookup undoes the rename sanitation did: every id on the page carries
 * `DOCUMENT_ID_PREFIX` and no `href` does. It is scoped to the document that
 * was clicked in, so a panel showing two files sends each link to its own.
 *
 * A link the document cannot answer -- to a heading that is not there, or to a
 * file's own anchors when only part of it is shown -- stops here rather than
 * navigating, which is the same nothing the reader saw before, minus the
 * address that had changed to say otherwise.
 */
function followLinkWithinDocument(event: React.MouseEvent<HTMLElement>): void {
  const href = (event.target as HTMLElement).closest("a")?.getAttribute("href");
  if (href === undefined || href === null || !href.startsWith("#")) return;
  event.preventDefault();

  const id = DOCUMENT_ID_PREFIX + fragmentOf(href);
  const target = event.currentTarget.querySelector(`#${CSS.escape(id)}`);
  if (!(target instanceof HTMLElement)) return;

  // Reading resumes from the heading, for a caret and a screen reader as well
  // as for the eye -- which is what the navigation this replaces would have
  // done. The focus is placed before the scroll and told not to scroll itself,
  // so the one move the reader sees is the animated one.
  target.tabIndex = -1;
  target.focus({ preventScroll: true });

  // Briefly animated, because the point of the motion is that the reader can
  // see where in the document they were carried from and to. A reader who has
  // asked their system for less of that is answered by the jump instead.
  const frame = scrollFrameOf(target);
  if (
    frame === null ||
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    target.scrollIntoView({ behavior: "auto", block: "start" });
    return;
  }
  carryTo(frame, target);
}

/**
 * Draw a markdown document, the way shadcn draws one.
 *
 * Rendering is synchronous and total: a document is a pure function of its
 * source, so it lands in the same paint as everything around it, and there is
 * no failure case to fall back from -- every string is a valid document.
 *
 * The two classes are the whole of the styling. `typeset` is what draws the
 * document, and takes its size from whatever is showing it -- 13px in a panel
 * row, where prose sits among inputs and has to line up with them, and larger
 * in a preview dialog, where the document is the only thing on screen; every
 * size in the stylesheet is written against that one. `reading-measure` is
 * Leika's, and is how wide the blocks are allowed to run, which is the one
 * question typeset leaves to the surface asking it.
 */
export function MarkdownRenderer(props: { children?: string }) {
  const source = props.children ?? "";
  const document = renderMarkdown(source);
  return (
    // One handler for the document rather than a component for its links: a
    // link into the same file is answered by where it lands, and where it
    // lands is only knowable from here.
    <div className="typeset reading-measure" onClick={followLinkWithinDocument}>
      {document}
    </div>
  );
}
