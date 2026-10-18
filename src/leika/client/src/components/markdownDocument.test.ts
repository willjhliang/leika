/**
 * The renderer's memory, and the one thing its components add to a document.
 *
 * What the pipeline produces is pinned in `markdown.test.ts`; here it is the
 * remembering -- identity across calls is what lets a reopened preview skip
 * the parse, and what lets React leave the DOM alone when a press's fresh
 * copy turns out to match what warming already showed -- and the size a
 * served figure reserves before it arrives.
 */

import { createElement } from "react";
import { PreviewImageSourcesContext } from "../previewImageSources";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, test, vi } from "vitest";

import { MARKDOWN_RENDER_MAX_SOURCE_BYTES } from "../markdown";
import {
  cachedMarkdownDocument,
  cachedPreviewText,
  MARKDOWN_CACHE_MAX_CHARS,
  MARKDOWN_WARM_MAX_ASSETS,
  MARKDOWN_WARM_MAX_BYTES,
  markdownSourceBytesAtMost,
  rememberMarkdownDocument,
  rememberPreviewText,
  renderMarkdown,
  resetMarkdownDocumentCache,
  warmMarkdownBlob,
} from "./markdownDocument";
import {
  MarkdownImage,
  MarkdownMediaController,
  MarkdownPicture,
} from "./MarkdownMedia";

const html = (markdown: string) =>
  renderToStaticMarkup(renderMarkdown(markdown).element);

const interactiveHtml = (markdown: string) =>
  renderToStaticMarkup(
    createElement(
      MarkdownMediaController,
      null,
      renderMarkdown(markdown).element,
    ),
  );

const figure = (
  width: number,
  height: number,
  linkedBy?: React.AnchorHTMLAttributes<HTMLAnchorElement>,
) =>
  createElement(MarkdownImage, {
    alt: "Plot",
    linkedBy,
    src: measuredAsset(width, height),
  });

const figureHtml = (width: number, height: number) =>
  renderToStaticMarkup(figure(width, height));

const interactiveFigureHtml = (
  width: number,
  height: number,
  linkedBy?: React.AnchorHTMLAttributes<HTMLAnchorElement>,
) =>
  renderToStaticMarkup(
    createElement(
      MarkdownMediaController,
      null,
      figure(width, height, linkedBy),
    ),
  );

const measuredAsset = (
  width: number,
  height: number,
  digest = "a".repeat(64),
) => `/leika-assets/${digest}-${width}x${height}.png?w=${width}&h=${height}`;

afterEach(() => {
  resetMarkdownDocumentCache();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function matching(markup: string, pattern: RegExp): string {
  const match = markup.match(pattern)?.[0];
  expect(match).toBeDefined();
  return match ?? "";
}

test("the same document answers with the same tree", () => {
  expect(renderMarkdown("# Setup\n\ntext")).toBe(
    renderMarkdown("# Setup\n\ntext"),
  );
});

test("a document no longer recent is rendered fresh", () => {
  const first = renderMarkdown("# evicted");
  for (let i = 0; i < 8; i++) renderMarkdown(`# filler ${i}`);
  expect(renderMarkdown("# evicted")).not.toBe(first);
});

test("UTF-8 render admission accepts the exact limit without an encoded copy", () => {
  expect(
    markdownSourceBytesAtMost(
      "x".repeat(MARKDOWN_RENDER_MAX_SOURCE_BYTES),
      MARKDOWN_RENDER_MAX_SOURCE_BYTES,
    ),
  ).toBe(MARKDOWN_RENDER_MAX_SOURCE_BYTES);
  expect(
    markdownSourceBytesAtMost(
      "x".repeat(MARKDOWN_RENDER_MAX_SOURCE_BYTES + 1),
      MARKDOWN_RENDER_MAX_SOURCE_BYTES,
    ),
  ).toBeNull();
  expect(markdownSourceBytesAtMost("🙂", 4)).toBe(4);
  expect(markdownSourceBytesAtMost("🙂", 3)).toBeNull();
});

test("oversized markdown gets a visible status without parsing", () => {
  const document = renderMarkdown(
    "x".repeat(MARKDOWN_RENDER_MAX_SOURCE_BYTES + 1),
  );
  const drawn = renderToStaticMarkup(document.element);
  expect(document.headings).toEqual([]);
  expect(drawn).toContain('role="status"');
  expect(drawn).toContain("1 MiB");
});

test("documents and preview text share one bound on the source they hold", () => {
  const document = renderMarkdown("# Report");
  const half = MARKDOWN_CACHE_MAX_CHARS / 2;
  const first = "a".repeat(half);
  const text = new Blob();
  rememberMarkdownDocument(first, document);
  rememberPreviewText(text, "b".repeat(half));
  // Touched, so the preview text is now the least recently used.
  expect(cachedMarkdownDocument(first)).toBe(document);
  rememberMarkdownDocument("c".repeat(half), document);

  expect(cachedPreviewText(text)).toBeNull();
  expect(cachedMarkdownDocument(first)).toBe(document);
  const tooLarge = "x".repeat(MARKDOWN_RENDER_MAX_SOURCE_BYTES + 1);
  rememberMarkdownDocument(tooLarge, document);
  expect(cachedMarkdownDocument(tooLarge)).toBeNull();
});

test("a preview's text is found by its exact Blob until reset", () => {
  const blob = new Blob(["# Report"]);
  rememberPreviewText(blob, "# Report");
  const document = renderMarkdown("# Report");
  expect(cachedPreviewText(blob)).toBe("# Report");
  expect(cachedPreviewText(new Blob(["# Report"]))).toBeNull();
  expect(cachedMarkdownDocument("# Report")).toBe(document);

  resetMarkdownDocumentCache();
  expect(cachedPreviewText(blob)).toBeNull();
  expect(cachedMarkdownDocument("# Report")).toBeNull();
});

test("reset drops rendered source and stops a warm decode from fetching", async () => {
  const fetch = vi.fn(() => Promise.resolve(new Response()));
  vi.stubGlobal("fetch", fetch);
  let resolveText!: (source: string) => void;
  const text = vi.fn(
    () =>
      new Promise<string>((resolve) => {
        resolveText = resolve;
      }),
  );
  warmMarkdownBlob({ size: 32, text } as unknown as Blob);
  resetMarkdownDocumentCache();
  resolveText("![plot](/leika-assets/a.png?w=1&h=1)");
  await Promise.resolve();

  expect(fetch).not.toHaveBeenCalled();
  const before = renderMarkdown("# after reset");
  resetMarkdownDocumentCache();
  expect(renderMarkdown("# after reset")).not.toBe(before);
});

test("warming prefetches each image once, within its bounds", async () => {
  const fetch = vi.fn(() => Promise.resolve(new Response()));
  vi.stubGlobal("fetch", fetch);
  const assets = Array.from(
    { length: MARKDOWN_WARM_MAX_ASSETS + 2 },
    (_, index) => `![${index}](/leika-assets/${index}.png?w=1&h=1)`,
  );
  assets.push(assets[0]);
  const source = assets.join("\n");
  warmMarkdownBlob({
    size: source.length,
    text: () => Promise.resolve(source),
  } as unknown as Blob);
  await Promise.resolve();

  expect(fetch).toHaveBeenCalledTimes(MARKDOWN_WARM_MAX_ASSETS);
  expect(fetch).toHaveBeenCalledWith("/leika-assets/0.png?w=1&h=1");

  const tooLargeText = vi.fn(() => Promise.resolve(""));
  warmMarkdownBlob({
    size: MARKDOWN_WARM_MAX_BYTES + 1,
    text: tooLargeText,
  } as unknown as Blob);
  expect(tooLargeText).not.toHaveBeenCalled();
});

test("a served figure reserves the size the server measured", () => {
  // The whole point of the exercise: the browser knows the shape of the box
  // before the picture is in it, so a document lays out once instead of
  // reflowing under the reader as each figure lands.
  const drawn = figureHtml(640, 360);
  expect(drawn).toContain('width="640"');
  expect(drawn).toContain('height="360"');
  expect(drawn).toContain('alt="Plot"');
});

test("measured figures load lazily and decode asynchronously", () => {
  const drawn = figureHtml(640, 360);
  expect(drawn).toContain('loading="lazy"');
  expect(drawn).toContain('decoding="async"');
  // Scheduling hints must not trade away the stable geometry that prevents
  // images arriving under the reader from moving the document.
  expect(drawn).toContain('width="640"');
  expect(drawn).toContain('height="360"');
});

test("an external figure is a link and causes no image request", () => {
  const drawn = html("![Plot](https://example.com/plot.png)");
  expect(drawn).toContain('href="https://example.com/plot.png"');
  expect(drawn).toContain(">Plot</a>");
  expect(drawn).not.toContain("<img");
});

test("a controlled figure has one accessible expand control", () => {
  const drawn = interactiveFigureHtml(8, 8);
  const surface = matching(
    drawn,
    /<span\b[^>]*data-leika-inline-media[^>]*>.*?<\/span>/,
  );

  expect(surface).toMatch(/^<span\b[^>]*><img\b/);
  expect(surface.match(/<button\b/g)).toHaveLength(1);
  expect(surface).toContain('aria-label="Expand image: Plot"');
});

test("a linked figure keeps link and expand as sibling actions", () => {
  const drawn = interactiveFigureHtml(8, 8, {
    href: "https://example.com/report",
  });
  const surface = matching(
    drawn,
    /<span\b[^>]*data-leika-inline-media[^>]*>.*?<\/span>/,
  );
  const link = matching(surface, /<a\b[^>]*>.*?<\/a>/);

  expect(surface).toMatch(
    /^<span\b[^>]*><a\b[^>]*><img\b[^>]*\/><\/a><button\b/,
  );
  expect(link).not.toContain("<button");
  expect(surface.match(/<button\b/g)).toHaveLength(1);
});

test("an ordinary text link remains ordinary", () => {
  const drawn = interactiveHtml("[Read report](https://example.com/report)");
  const link = matching(drawn, /<a\b[^>]*>.*?<\/a>/);

  expect(link).toContain('href="https://example.com/report"');
  expect(link).toContain(">Read report</a>");
  expect(link).not.toContain("<button");
});

test("a controlled picture drops source selection and admits only its fallback", () => {
  const drawn = renderToStaticMarkup(
    createElement(
      MarkdownMediaController,
      null,
      createElement(
        MarkdownPicture,
        null,
        createElement("source", {
          srcSet: "https://example.com/wide.png 2x",
        }),
        figure(8, 8),
      ),
    ),
  );
  expect(drawn).not.toContain("<picture");
  expect(drawn).not.toContain("<source");
  expect(drawn).not.toContain("example.com/wide.png");
  expect(drawn).toContain("<img");
  expect(drawn).toContain("data-leika-inline-media");
});

test("a caption under a figure is still markdown", () => {
  // Why the size travels in the URL rather than in an `<img>` written into
  // the document: a tag on a line of its own opens an HTML block, and
  // everything down to the next blank line stops being parsed.
  const drawn = html(`![Plot](${measuredAsset(8, 8)})\n*Figure 1*`);
  expect(drawn).toContain("<em>Figure 1</em>");
});

test("worker-cloned Markdown uses the same sanitation, headings, and rendering", async () => {
  const { parseMarkdown } = await import("../markdown");
  const { compileMarkdown } = await import("./markdownDocument");
  const source =
    "# Heading\n\n<script>alert(1)</script>\n\n[unsafe](javascript:alert(1))\n\n![plot](relative.png)\n\n## Section\n\n|a|b|\n|-|-|\n|1|2|";
  const parsed = structuredClone(parseMarkdown(source));
  const compiled = compileMarkdown(parsed);
  expect(renderToStaticMarkup(compiled.element)).toBe(
    renderToStaticMarkup(renderMarkdown(source).element),
  );
  expect(compiled.headings).toEqual(renderMarkdown(source).headings);
  const lead = renderToStaticMarkup(
    createElement(
      PreviewImageSourcesContext.Provider,
      { value: { pending: true } },
      compiled.element,
    ),
  );
  expect(lead).toContain("Heading");
  expect(lead).not.toContain("<img");
  expect(lead).not.toContain("<script");
  expect(lead).not.toContain("javascript:");
});
