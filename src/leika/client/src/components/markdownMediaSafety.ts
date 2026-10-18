import type { MediaSize } from "./mediaPreviewSize";

export interface MarkdownImageSource {
  kind: "asset" | "data" | "blocked";
  /** The size the server measured for an asset, or null. */
  size: MediaSize | null;
}

/** Whether a document's image is drawn, decided without fetching it.
 *
 * Leika's own assets and inline `data:image/` URLs are drawn. Anything else --
 * a remote or relative URL -- stays a link, so opening a document never makes
 * a request the reader did not ask for.
 *
 * An asset's measured size travels in its URL as a query rather than in an
 * HTML tag, because a tag on a line of its own opens an HTML block in
 * Markdown. The query is invisible to the parser and ignored by the asset
 * server, while giving the browser a stable box before the pixels arrive.
 */
export function markdownImageSource(
  src: string | undefined,
): MarkdownImageSource {
  if (src?.startsWith("/leika-assets/")) {
    const measured = /[?&]w=(\d+)&h=(\d+)/.exec(src);
    return {
      kind: "asset",
      size:
        measured === null
          ? null
          : { width: Number(measured[1]), height: Number(measured[2]) },
    };
  }
  return {
    kind: src?.startsWith("data:image/") ? "data" : "blocked",
    size: null,
  };
}
