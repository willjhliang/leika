/**
 * The one renderer documents share, and its memory.
 *
 * Apart from `MarkdownRenderer` so that things that are not components -- the
 * message handler warming a file ahead of its press, a test pinning identity
 * -- can reach the renderer without importing a component file (which React's
 * fast refresh wants left to components alone).
 */

import {
  createMarkdownRenderer,
  type MarkdownComponents,
  type RenderedDocument,
} from "../markdown";
import { MAX_GUI_MARKDOWN_SOURCE_BYTES } from "../guiLimits";
import { MarkdownImage, MarkdownLink, MarkdownPicture } from "./MarkdownMedia";

// What a document looks like is shadcn/typeset's, whole: `src/typeset.css`
// draws every element markdown makes -- the heading scale, the leading, the
// space between blocks, the rules on a table, the underline on a link -- from
// three values, and Leika sets none of them. There is nothing here that says
// how a document looks, and nothing here should be.
//
// A component is worth writing only for what a tag *does*, or for structure a
// stylesheet cannot add for itself. There are four.
const components: MarkdownComponents = {
  // A document can be opened on a file from anywhere, and a link in one is a
  // link out of Leika. The referrer is the one thing following it should not
  // carry with it.
  a: MarkdownLink,
  // A figure served beside its document has no size until it has arrived, so
  // the browser leaves it no room and lays the document out again when it
  // lands -- under the reader, who has been reading since the text arrived.
  // The server measures what it serves and says so in the URL; this is where
  // that becomes the width and height the browser reserves from. See
  // `_link_markdown_assets`, and MarkdownImage for why it travels
  // there rather than in the tag.
  // Warming still fetches every immutable image URL ahead of a press, but
  // fetching bytes and decoding them are separate browser costs. Ask the
  // browser to leave a measured offscreen image encoded until it approaches
  // the viewport, and never make its decode block the document's paint. Only a
  // Leika asset is already warm, and only a measured one has a box to hold its
  // place; every external or unmeasured image keeps its prior eager behavior.
  // Neither hint changes a served image's box or styling.
  img: MarkdownImage,
  picture: MarkdownPicture,
  // typeset holds a table's headings on one line, so a table with long ones
  // is wider than the page whatever the page does, and the wrapper is what it
  // ships to say where that width is allowed to go: the table scrolls inside
  // its own box instead of the document scrolling sideways and taking every
  // paragraph in it along. Markdown cannot tell us which tables are wide, so
  // every one gets it -- the box is only a scroll when there is something to
  // scroll. The wrapper owns the space above it, which is why the table
  // itself no longer carries any.
  table: (props) => (
    <div className="typeset-scroll">
      <table {...props} />
    </div>
  ),
};

const render = createMarkdownRenderer(components);

/** How many rendered documents are kept. Reading during a run means the same
 * report opened over and over; a handful of documents is a session's worth,
 * and holding elements for more would hold their whole trees in memory. */
const RENDERED_LIMIT = 8;
/** Bound parsed Markdown by source size as well as cached source bytes. Even
 * compact Markdown can expand into many React/DOM nodes, so this is lower
 * than the 16 MiB plain-text preview ceiling. */
export const MARKDOWN_RENDER_MAX_SOURCE_BYTES = MAX_GUI_MARKDOWN_SOURCE_BYTES;
export const MARKDOWN_CACHE_MAX_SOURCE_BYTES = 2 * 1024 * 1024;
export const MARKDOWN_CACHE_MAX_ENTRY_BYTES = 512 * 1024;
export const MARKDOWN_WARM_MAX_BYTES = 512 * 1024;
export const MARKDOWN_WARM_MAX_ASSETS = 128;
type CachedDocument = { document: RenderedDocument; sourceBytes: number };
const rendered = new Map<string, CachedDocument>();
let renderedSourceBytes = 0;
let warmBlobInFlight = false;
let warmDocumentInFlight = false;
let warmGeneration = 0;
const pendingWarmIdleCancellations = new Set<() => void>();

export function markdownRenderAllowed(sizeBytes: number): boolean {
  return sizeBytes <= MARKDOWN_RENDER_MAX_SOURCE_BYTES;
}

/** Count UTF-8 bytes without allocating an equally large encoded copy. */
export function markdownSourceBytesAtMost(
  source: string,
  maximum: number,
): number | null {
  let bytes = 0;
  for (let index = 0; index < source.length; index += 1) {
    const first = source.charCodeAt(index);
    if (first < 0x80) bytes += 1;
    else if (first < 0x800) bytes += 2;
    else if (first >= 0xd800 && first <= 0xdbff) {
      const second = source.charCodeAt(index + 1);
      if (second >= 0xdc00 && second <= 0xdfff) {
        bytes += 4;
        index += 1;
      } else {
        bytes += 3;
      }
    } else bytes += 3;
    if (bytes > maximum) return null;
  }
  return bytes;
}

/** Turn markdown into elements, remembering the documents recently shown.
 *
 * Parsing a long document is the one real cost left in opening one, and it
 * was being paid again on every reopening of the same unchanged file. The
 * elements are immutable, so the same source may answer with the same tree
 * every time; a document whose text has changed -- including an image
 * updating, since images are referenced by content-addressed URLs that
 * change with them -- is a different key and renders fresh.
 */
export function renderMarkdown(source: string): RenderedDocument {
  const cached = rendered.get(source);
  if (cached !== undefined) {
    // Reinsert so the map's order stays the order of last use.
    rendered.delete(source);
    rendered.set(source, cached);
    return cached.document;
  }
  const bytes = markdownSourceBytesAtMost(
    source,
    MARKDOWN_RENDER_MAX_SOURCE_BYTES,
  );
  if (bytes === null) {
    return {
      element: (
        <p role="status">
          This document is over the 1 MiB in-browser markdown render limit.
        </p>
      ),
      headings: [],
    };
  }
  const document = render(source);
  if (bytes <= MARKDOWN_CACHE_MAX_ENTRY_BYTES) {
    rendered.set(source, { document, sourceBytes: bytes });
    renderedSourceBytes += bytes;
  }
  while (
    rendered.size > RENDERED_LIMIT ||
    renderedSourceBytes > MARKDOWN_CACHE_MAX_SOURCE_BYTES
  ) {
    const oldestKey = rendered.keys().next().value!;
    const oldest = rendered.get(oldestKey)!;
    rendered.delete(oldestKey);
    renderedSourceBytes -= oldest.sourceBytes;
  }
  return document;
}

export function resetMarkdownDocumentCache(): void {
  rendered.clear();
  renderedSourceBytes = 0;
  warmGeneration += 1;
  for (const cancel of [...pendingWarmIdleCancellations]) cancel();
}

/** Ready a document before anyone has asked to read it.
 *
 * The two costs of a first open are paid here, ahead of the click: the parse
 * goes into the render cache, and the images the document names are fetched
 * so the browser's own cache holds them -- their URLs are immutable, so what
 * is fetched now is exactly what the open will show. The parse waits for an
 * idle moment because warming happens while the reader is doing something
 * else, and must not be felt.
 *
 * The URLs are matched with their `?w=&h=` if they carry one, because that is
 * the address the document will ask for: fetching the bare path would warm a
 * cache entry under a key no `<img>` on the page is going to use.
 */
export function warmMarkdownDocument(
  source: string,
  ownerIsActive: () => boolean = () => true,
): Promise<void> {
  if (
    warmDocumentInFlight ||
    markdownSourceBytesAtMost(source, MARKDOWN_WARM_MAX_BYTES) === null
  )
    return Promise.resolve();
  warmDocumentInFlight = true;
  const generation = warmGeneration;
  return new Promise<void>((resolve) => {
    let settled = false;
    let cancelScheduled: () => void = () => undefined;
    let cancel: () => void = () => undefined;
    const finish = () => {
      if (settled) return;
      settled = true;
      pendingWarmIdleCancellations.delete(cancel);
      warmDocumentInFlight = false;
      resolve();
    };
    const work = () => {
      if (settled) return;
      try {
        if (generation !== warmGeneration || !ownerIsActive()) return;
        renderMarkdown(source);
        const urls = new Set(
          source.match(/\/leika-assets\/[\w.-]+(?:\?w=\d+&h=\d+)?/g) ?? [],
        );
        let count = 0;
        for (const url of urls) {
          if (count >= MARKDOWN_WARM_MAX_ASSETS) break;
          count += 1;
          try {
            void fetch(url).catch(() => undefined);
          } catch {
            // No browser to cache for (tests); nothing to warm.
          }
        }
      } catch {
        // Warming is opportunistic. The foreground renderer remains the
        // authoritative error surface if a future parser rejects a document.
      } finally {
        finish();
      }
    };
    try {
      if (
        typeof requestIdleCallback === "function" &&
        typeof cancelIdleCallback === "function"
      ) {
        const handle = requestIdleCallback(work);
        cancelScheduled = () => cancelIdleCallback(handle);
      } else {
        const handle = setTimeout(work, 100);
        cancelScheduled = () => clearTimeout(handle);
      }
    } catch {
      finish();
    }
    cancel = () => {
      if (settled) return;
      try {
        cancelScheduled();
      } catch {
        // Cleanup remains complete if a browser scheduler rejects cancellation.
      } finally {
        finish();
      }
    };
    if (!settled) pendingWarmIdleCancellations.add(cancel);
  });
}

/** Decode at most one small warm Blob at a time. Evicted warm owners cannot
 * populate the markdown cache after their byte reservation has gone away. */
export function warmMarkdownBlob(
  blob: Blob,
  ownerIsActive: () => boolean,
): void {
  if (
    blob.size > MARKDOWN_WARM_MAX_BYTES ||
    warmBlobInFlight ||
    !ownerIsActive()
  )
    return;
  const generation = warmGeneration;
  warmBlobInFlight = true;
  let decoded: Promise<string>;
  try {
    decoded = blob.text();
  } catch {
    warmBlobInFlight = false;
    return;
  }
  void decoded
    .then(
      (source) => {
        if (generation === warmGeneration && ownerIsActive()) {
          return warmMarkdownDocument(source, ownerIsActive);
        }
      },
      () => undefined,
    )
    .finally(() => {
      warmBlobInFlight = false;
    });
}
