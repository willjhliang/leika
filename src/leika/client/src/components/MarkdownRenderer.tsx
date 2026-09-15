import React from "react";

import { cn } from "@/lib/utils";
import {
  contentsOf,
  DOCUMENT_ID_PREFIX,
  type DocumentHeading,
  type RenderedDocument,
} from "../markdown";
import { renderMarkdown } from "./markdownDocument";
import { cancelMarkdownCarry, startMarkdownCarry } from "./markdownCarry";
import { MarkdownMediaController } from "./MarkdownMedia";
import {
  sectionAtScroll,
  type MeasuredSection,
  type SectionLayout,
} from "./markdownSectionLayout";

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

/** The box the document is read through, whether or not it is scrolled.
 *
 * The frame a reader sees the document in. {@link scrollFrameOf} answers a
 * different question with almost the same walk -- which box a carry should
 * move -- and wants the first ancestor that is *actually* overflowing, since
 * a frame with nothing to scroll is not the one a link should move. Here the
 * frame is wanted for its edges, and a document that happens to fit in it has
 * edges like any other.
 */
function readingFrameOf(element: HTMLElement): HTMLElement | null {
  for (
    let node = element.parentElement;
    node !== null;
    node = node.parentElement
  ) {
    const { overflowY } = getComputedStyle(node);
    if (overflowY === "auto" || overflowY === "scroll") return node;
  }
  return null;
}

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
function followLinkWithinDocument(
  event: React.MouseEvent<HTMLElement>,
  carryOwner: object,
): void {
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
    cancelMarkdownCarry();
    target.scrollIntoView({ behavior: "auto", block: "start" });
    return;
  }
  startMarkdownCarry(frame, target, carryOwner);
}

/** Measure headings once, after layout changes, in document coordinates. */
function measureSectionLayout(
  frame: HTMLElement,
  headings: DocumentHeading[],
): SectionLayout {
  const box = frame.getBoundingClientRect();
  const scrollTop = frame.scrollTop;
  const sections: MeasuredSection[] = [];
  let ordered = true;
  let previousTop = -Infinity;
  for (const heading of headings) {
    const id = CSS.escape(DOCUMENT_ID_PREFIX + heading.fragment);
    const element = frame.querySelector(`#${id}`);
    if (!(element instanceof HTMLElement)) continue;
    const top = element.getBoundingClientRect().top - box.top + scrollTop;
    ordered &&= top >= previousTop;
    previousTop = top;
    sections.push({ fragment: heading.fragment, top });
  }
  return {
    first: headings[0]?.fragment ?? null,
    sections,
    ordered,
    viewportHeight: box.height,
    clientHeight: frame.clientHeight,
    scrollHeight: frame.scrollHeight,
  };
}

/** Which of `headings` the reader is currently in front of.
 *
 * Measured rather than observed. An `IntersectionObserver` answers "is this
 * heading on screen", which is not the question: a section longer than the
 * frame has no heading on screen anywhere in the middle of it, and the
 * contents list would go blank for exactly as long as the reader stayed in
 * the section they were reading. What is wanted is the last heading that has
 * gone past the line, which is always some heading, and is the one whose
 * words are above whatever is in front of the reader now.
 *
 * The end of the document needs saying twice, not differently. A file whose
 * last sections are shorter than the frame cannot scroll their headings up to
 * the line at all -- the scroll runs out first -- and the rule above would
 * leave the mark on a section that is no longer on the screen, which is the
 * one thing it must never do. So at the bottom of the scroll the same
 * question is asked of what is visible: the topmost heading still on screen
 * is the section at the top of the view, line or no line. A last section long
 * enough to fill the frame is unaffected, having no heading on screen to
 * prefer.
 */
function useCurrentSection(
  headings: DocumentHeading[],
  navRef: React.RefObject<HTMLElement | null>,
): string | null {
  const [current, setCurrent] = React.useState<string | null>(null);
  React.useEffect(() => {
    const nav = navRef.current;
    if (nav === null) return;
    const frame = readingFrameOf(nav);
    if (frame === null) return;

    let pending = 0;
    let layout = measureSectionLayout(frame, headings);
    let layoutChanged = false;
    // The entry the list was last moved for. Kept so that it is only moved
    // when the answer changes -- see {@link keepInView}.
    let moved: string | null = null;
    const select = () => {
      pending = 0;
      if (layoutChanged) {
        layout = measureSectionLayout(frame, headings);
        layoutChanged = false;
      }
      const reached = sectionAtScroll(layout, frame.scrollTop);
      setCurrent(reached);
      if (reached !== moved) {
        moved = reached;
        keepInView(nav, reached);
      }
    };
    const schedule = () => {
      if (pending === 0) pending = requestAnimationFrame(select);
    };
    const remeasure = () => {
      layoutChanged = true;
      schedule();
    };
    select();
    frame.addEventListener("scroll", schedule, { passive: true });
    // The document itself changes size -- a preview follows the file it was
    // read from, and a section can be written while it is being read -- and
    // that moves every heading under the reader without a scroll to say so.
    const resizes = new ResizeObserver(remeasure);
    resizes.observe(frame);
    const document_ = frame.querySelector(".typeset");
    if (document_ !== null) resizes.observe(document_);
    return () => {
      if (pending !== 0) cancelAnimationFrame(pending);
      frame.removeEventListener("scroll", schedule);
      resizes.disconnect();
    };
  }, [headings, navRef]);
  return current;
}

/** Keep the marked entry inside the contents list's own scroll.
 *
 * A list longer than the window scrolls on its own, and the whole use of
 * marking an entry is being able to see it. Moved by hand rather than with
 * `scrollIntoView`, which scrolls every scrollable ancestor it needs to --
 * including the frame holding the document, which would mean the contents
 * list scrolling the thing that is scrolling it.
 *
 * Called when the mark MOVES, and not otherwise, which is what makes the two
 * scrolls independent. A reader who scrolls the list to look further down the
 * file has left the marked entry off the top of it, so every section check
 * after that -- and one runs on every frame the document scrolls in --
 * found the entry out of view and hauled the list back to it. Reading on by a
 * line snapped the list shut. Only a new section is a reason to move it, and
 * a new section is a reason: the mark is no use where it cannot be seen.
 */
function keepInView(nav: HTMLElement, fragment: string | null): void {
  if (fragment === null) return;
  const entry = nav.querySelector(`a[href="#${CSS.escape(fragment)}"]`);
  if (!(entry instanceof HTMLElement)) return;
  const list = nav.getBoundingClientRect();
  const box = entry.getBoundingClientRect();
  if (box.top < list.top) nav.scrollTop -= list.top - box.top;
  else if (box.bottom > list.bottom) nav.scrollTop += box.bottom - list.bottom;
}

/** The document's headings, in a column to the right of it.
 *
 * A column of its own rather than something floating in the margin: a table
 * takes the whole width it is given, so a list hanging over the margin would
 * be a list hanging over the table. The document and the list are then
 * centred in the frame together, so standing the list up moves the writing
 * left by half of what the list takes -- the reader is looking at a document
 * with a list beside it, and that pair is what the popup is showing.
 *
 * It stays put while the document moves under it, which is the whole use of
 * it -- a contents list you have to scroll back up to is the one at the top of
 * the file. Its own scroll is its own: `overscroll-contain` keeps the end of
 * a long list from being passed outwards to the document behind it, and the
 * mark only pulls the list about when the mark itself moves; see
 * {@link keepInView}. The height it may take is the window's less the popup's
 * chrome, because what it sticks to is the frame the document scrolls in, and
 * that is as tall as the window lets it be.
 *
 * It carries no heading of its own. A column of the file's own words beside
 * the file: nothing about that needs announcing, and "Contents" over it would
 * be the only word on the screen that the document did not write. Screen
 * readers are told, since they cannot see the shape of it.
 */
function DocumentContents({ headings }: { headings: DocumentHeading[] }) {
  let shallowest = Number.POSITIVE_INFINITY;
  for (const heading of headings) {
    shallowest = Math.min(shallowest, heading.level);
  }
  const navRef = React.useRef<HTMLElement>(null);
  const current = useCurrentSection(headings, navRef);
  return (
    <nav
      ref={navRef}
      aria-label="Contents"
      // Reserve the sidebar only when there is enough room for it and a
      // full reading measure in the content section. Narrow previews keep
      // the entire width for the document, even when contents are requested.
      className="sticky top-0 hidden max-h-[calc(100dvh-6rem)] self-start overflow-y-auto overscroll-contain pt-1 no-scrollbar @min-[67rem]/document:col-start-2 @min-[67rem]/document:row-start-1 @min-[67rem]/document:block"
      data-leika-document-contents
    >
      {/* Set at label size -- `text-sm`, which this app draws at 13px -- and
          not at the size of the document beside it. These are not part of the
          writing: they name its parts, the way a field's label names the
          field, and a column of them set as large as the prose reads as a
          second document competing with the first. */}
      <ul className="text-sm">
        {headings.map((heading) => (
          <li key={heading.fragment}>
            {/* An ordinary in-document link, so the click is answered by the
                handler below exactly as a link written in the file is: the
                document scrolls itself, and the address bar stays the app's. */}
            <a
              href={`#${heading.fragment}`}
              aria-current={heading.fragment === current ? "true" : undefined}
              // Colour, and no weight: this column is narrow enough that
              // entries wrap, and a heading that re-wrapped as you scrolled
              // past it would move every entry under it.
              className={cn(
                "block py-1 leading-snug transition-colors",
                heading.fragment === current
                  ? "text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
              style={{
                paddingLeft: `${0.75 + (heading.level - shallowest) * 0.75}rem`,
              }}
            >
              {heading.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
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
 *
 * `contents` stands the document's headings up beside it, which is a thing
 * to ask for only where there is room for them: a preview dialog has room, a
 * panel row is the width of a panel. It is the reader's answer, kept per file
 * -- see ./previewContents -- and it is still only a request: whether the
 * room is there on the day is settled in CSS (see {@link DocumentContents}),
 * and a document with too few headings to make a list of has nothing to stand
 * up either way.
 */
export function MarkdownRenderer(props: {
  children?: string;
  contents?: boolean;
  /** Reuse the preview's parse, including documents too large to cache. */
  document?: RenderedDocument;
}) {
  const source = props.children ?? "";
  const carryOwner = React.useRef<object>(null);
  if (carryOwner.current === null) carryOwner.current = {};
  React.useEffect(
    () => () => cancelMarkdownCarry(carryOwner.current ?? undefined),
    [],
  );
  const { element, headings } = React.useMemo(
    () => props.document ?? renderMarkdown(source),
    [props.document, source],
  );
  // Held still across renders, because it is what the marking of the current
  // section watches: a fresh array every render is a fresh set of listeners
  // every render. `headings` is already the same array for the same document,
  // the render cache having answered with the same document.
  const wanted = props.contents === true;
  const listed = React.useMemo(
    () => (wanted ? contentsOf(headings) : []),
    [wanted, headings],
  );

  // One handler for the whole of it rather than a component for its links: a
  // link into the same file is answered by where it lands, and where it lands
  // is only knowable from here. A contents entry is such a link, so it sits
  // inside the same handler and needs nothing of its own.
  //
  // Keep the document mounted when the sidebar is toggled so loaded figures,
  // selection, and scroll anchors survive. Only the layout classes change.
  const showing = listed.length > 0;
  return (
    <MarkdownMediaController>
      <div
        className="@container/document"
        onClick={(event) =>
          followLinkWithinDocument(event, carryOwner.current!)
        }
      >
        {/* The contents are placed in the second column rather than written
          there: first in the document, so that reaching them does not mean
          reading past the file to get to them, and last on the screen, where
          they were asked for.

          The content section fills the space beside the fixed-width sidebar.
          Its blocks centre themselves within that section using equal inline
          margins, just as they do across the whole surface when contents are
          hidden. Wide tables may use the section's full width. Neither section
          is sized from the blocks arriving during streaming. */}
        <div
          className={cn(
            showing &&
              "grid @min-[67rem]/document:grid-cols-[minmax(0,1fr)_10rem] @min-[67rem]/document:gap-x-6",
          )}
        >
          {showing ? <DocumentContents headings={listed} /> : null}
          {/* Both placed by hand, and both told which row: auto-placement fills
            forwards only, so a document asking for the column to the left of
            the contents would be put on the row below them. */}
          <div
            className={cn(
              "typeset reading-measure",
              showing &&
                "@min-[67rem]/document:col-start-1 @min-[67rem]/document:row-start-1 @min-[67rem]/document:min-w-0",
            )}
          >
            {element}
          </div>
        </div>
      </div>
    </MarkdownMediaController>
  );
}
