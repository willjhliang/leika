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
  createMarkdownCompiler,
  MARKDOWN_RENDER_MAX_SOURCE_BYTES,
  type MarkdownComponents,
  type RenderedDocument,
} from "../markdown";
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
  // `_link_markdown_assets`, and markdownImageSource for why it travels
  // there rather than in the tag. Streamed previews resolve each source
  // through context, keeping the same component and DOM when the final
  // document arrives.
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
export const compileMarkdown = createMarkdownCompiler(components);

/** How many entries the cache keeps. Reading during a run means the same
 * report opened over and over; a handful of documents is a session's worth,
 * and holding elements for more would hold their whole trees in memory. */
const CACHE_LIMIT = 8;
/** The cache's bound on the source it holds, in UTF-16 code units: room for
 * two documents at the render limit. */
export const MARKDOWN_CACHE_MAX_CHARS = 2 * MARKDOWN_RENDER_MAX_SOURCE_BYTES;
export const MARKDOWN_WARM_MAX_BYTES = 512 * 1024;
export const MARKDOWN_WARM_MAX_ASSETS = 128;

/** The documents recently shown, least recently used first.
 *
 * A source keys its parse. A Blob keys the text a preview read out of it, so
 * reopening a file finds its parse with neither a read nor a reparse. The
 * parse is immutable, so the same source may answer with the same tree every
 * time; a document whose text has changed -- including an image updating,
 * since images are referenced by content-addressed URLs that change with
 * them -- is a different key and renders fresh.
 */
type CacheEntry = { source: string; document: RenderedDocument | null };
const cache = new Map<string | Blob, CacheEntry>();
let cachedChars = 0;
let warmGeneration = 0;

function cached(key: string | Blob): CacheEntry | undefined {
  const entry = cache.get(key);
  if (entry !== undefined) {
    // Reinsert so the map's order stays the order of last use.
    cache.delete(key);
    cache.set(key, entry);
  }
  return entry;
}

function remember(key: string | Blob, entry: CacheEntry): void {
  const replaced = cache.get(key);
  if (replaced !== undefined) cachedChars -= replaced.source.length;
  cache.delete(key);
  // Text past the render limit -- a long log being previewed -- would push
  // out everything else.
  if (entry.source.length > MARKDOWN_RENDER_MAX_SOURCE_BYTES) return;
  cache.set(key, entry);
  cachedChars += entry.source.length;
  while (cache.size > CACHE_LIMIT || cachedChars > MARKDOWN_CACHE_MAX_CHARS) {
    const [oldestKey, oldest] = cache.entries().next().value!;
    cache.delete(oldestKey);
    cachedChars -= oldest.source.length;
  }
}

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
 * was being paid again on every reopening of the same unchanged file.
 */
export function renderMarkdown(source: string): RenderedDocument {
  const known = cached(source)?.document;
  if (known) return known;
  if (
    markdownSourceBytesAtMost(source, MARKDOWN_RENDER_MAX_SOURCE_BYTES) === null
  ) {
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
  remember(source, { source, document });
  return document;
}

/** The parse of `source`, if it is still remembered. */
export function cachedMarkdownDocument(
  source: string,
): RenderedDocument | null {
  return cached(source)?.document ?? null;
}

/** Remember a parse made elsewhere -- a preview's, made in a worker. */
export function rememberMarkdownDocument(
  source: string,
  document: RenderedDocument,
): void {
  remember(source, { source, document });
}

/** The text a preview read out of `blob`, if it is still remembered. */
export function cachedPreviewText(blob: Blob): string | null {
  return cached(blob)?.source ?? null;
}

export function rememberPreviewText(blob: Blob, text: string): void {
  remember(blob, { source: text, document: null });
}

export function resetMarkdownDocumentCache(): void {
  cache.clear();
  cachedChars = 0;
  warmGeneration += 1;
}

/** Fetch a warmed document's images before anyone has asked to read it.
 *
 * Their URLs are immutable, so what the browser caches now is exactly what
 * the open will show; the document itself is parsed by the preview that
 * opens it. The URLs are matched with their `?w=&h=` if they carry one,
 * because that is the address the document will ask for: fetching the bare
 * path would warm a cache entry under a key no `<img>` on the page is going
 * to use.
 */
export function warmMarkdownBlob(blob: Blob): void {
  if (blob.size > MARKDOWN_WARM_MAX_BYTES) return;
  const generation = warmGeneration;
  void blob.text().then((source) => {
    // A reconnect may have replaced the server these URLs belong to.
    if (generation !== warmGeneration) return;
    const urls = new Set(
      source.match(/\/leika-assets\/[\w.-]+(?:\?w=\d+&h=\d+)?/g),
    );
    for (const url of [...urls].slice(0, MARKDOWN_WARM_MAX_ASSETS)) {
      void fetch(url).catch(() => undefined);
    }
  });
}
