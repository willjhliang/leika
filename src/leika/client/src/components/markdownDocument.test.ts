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
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, test, vi } from "vitest";

import {
  MARKDOWN_CACHE_MAX_ENTRY_BYTES,
  MARKDOWN_CACHE_MAX_SOURCE_BYTES,
  MARKDOWN_RENDER_MAX_SOURCE_BYTES,
  MARKDOWN_WARM_MAX_ASSETS,
  MARKDOWN_WARM_MAX_BYTES,
  markdownSourceBytesAtMost,
  renderMarkdown,
  resetMarkdownDocumentCache,
  warmMarkdownBlob,
  warmMarkdownDocument,
} from "./markdownDocument";
import {
  AdmittedMarkdownImage,
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

const admittedImage = (
  width: number,
  height: number,
  linkedBy?: React.AnchorHTMLAttributes<HTMLAnchorElement>,
) =>
  createElement(AdmittedMarkdownImage, {
    alt: "Plot",
    linkedBy,
    measured: { width, height },
    sourceKind: "asset",
    src: measuredAsset(width, height),
  });

const admittedHtml = (width: number, height: number) =>
  renderToStaticMarkup(admittedImage(width, height));

const interactiveAdmittedHtml = (
  width: number,
  height: number,
  linkedBy?: React.AnchorHTMLAttributes<HTMLAnchorElement>,
) =>
  renderToStaticMarkup(
    createElement(
      MarkdownMediaController,
      null,
      admittedImage(width, height, linkedBy),
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

test("the rendered cache has entry and aggregate source-byte bounds", () => {
  const sources = Array.from(
    { length: 5 },
    (_, index) =>
      `# ${index}\n\n${"x".repeat(MARKDOWN_CACHE_MAX_ENTRY_BYTES - 8)}`,
  );
  const first = renderMarkdown(sources[0]);
  for (const source of sources.slice(1)) renderMarkdown(source);

  expect(MARKDOWN_CACHE_MAX_SOURCE_BYTES).toBe(
    4 * MARKDOWN_CACHE_MAX_ENTRY_BYTES,
  );
  expect(renderMarkdown(sources[0])).not.toBe(first);

  const oversizedEntry = "z".repeat(MARKDOWN_CACHE_MAX_ENTRY_BYTES + 1);
  expect(renderMarkdown(oversizedEntry)).not.toBe(
    renderMarkdown(oversizedEntry),
  );
});

test("reset drops rendered source and invalidates pending warm parsing", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn(() => Promise.resolve(new Response()));
  vi.stubGlobal("fetch", fetch);
  let resolveText!: (source: string) => void;
  const text = vi.fn(
    () =>
      new Promise<string>((resolve) => {
        resolveText = resolve;
      }),
  );
  const blob = { size: 32, text } as unknown as Blob;
  warmMarkdownBlob(blob, () => true);
  resetMarkdownDocumentCache();
  resolveText("![plot](/leika-assets/a.png?w=1&h=1)");
  await Promise.resolve();
  await Promise.resolve();
  vi.runAllTimers();

  expect(fetch).not.toHaveBeenCalled();
  const before = renderMarkdown("# after reset");
  resetMarkdownDocumentCache();
  expect(renderMarkdown("# after reset")).not.toBe(before);
});

test("warm Blob parsing is size-bounded and single-flight", async () => {
  vi.useFakeTimers();
  let resolveFirst!: (source: string) => void;
  const firstText = vi.fn(
    () => new Promise<string>((resolve) => (resolveFirst = resolve)),
  );
  const secondText = vi.fn(() => Promise.resolve("# second"));
  warmMarkdownBlob(
    { size: MARKDOWN_WARM_MAX_BYTES, text: firstText } as unknown as Blob,
    () => true,
  );
  warmMarkdownBlob(
    { size: 1, text: secondText } as unknown as Blob,
    () => true,
  );
  expect(firstText).toHaveBeenCalledOnce();
  expect(secondText).not.toHaveBeenCalled();
  resolveFirst("# discarded");
  await Promise.resolve();
  await Promise.resolve();
  // Decoding remains single-flight until the scheduled parse has actually
  // run; otherwise each hidden-tab idle closure could retain another source.
  warmMarkdownBlob(
    { size: 1, text: secondText } as unknown as Blob,
    () => true,
  );
  expect(secondText).not.toHaveBeenCalled();
  await vi.runAllTimersAsync();
  warmMarkdownBlob(
    { size: 1, text: secondText } as unknown as Blob,
    () => true,
  );
  expect(secondText).toHaveBeenCalledOnce();
  await Promise.resolve();
  await Promise.resolve();
  await vi.runAllTimersAsync();

  const tooLargeText = vi.fn(() => Promise.resolve("# too large"));
  warmMarkdownBlob(
    {
      size: MARKDOWN_WARM_MAX_BYTES + 1,
      text: tooLargeText,
    } as unknown as Blob,
    () => true,
  );
  expect(tooLargeText).not.toHaveBeenCalled();

  const evictedText = vi.fn(() => Promise.resolve("# evicted"));
  warmMarkdownBlob(
    { size: 1, text: evictedText } as unknown as Blob,
    () => false,
  );
  expect(evictedText).not.toHaveBeenCalled();
});

test("an evicted owner cancels warm work already queued for idle", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn(() => Promise.resolve(new Response()));
  vi.stubGlobal("fetch", fetch);
  let active = true;
  warmMarkdownBlob(
    {
      size: 48,
      text: () => Promise.resolve("![plot](/leika-assets/late.png?w=1&h=1)"),
    } as unknown as Blob,
    () => active,
  );
  await Promise.resolve();
  await Promise.resolve();
  active = false;
  vi.runAllTimers();

  expect(fetch).not.toHaveBeenCalled();
});

test("markdown warming deduplicates and caps asset prefetches", async () => {
  vi.useFakeTimers();
  const fetch = vi.fn(() => Promise.resolve(new Response()));
  vi.stubGlobal("fetch", fetch);
  const assets = Array.from(
    { length: MARKDOWN_WARM_MAX_ASSETS + 2 },
    (_, index) => `![${index}](/leika-assets/${index}.png)`,
  );
  assets.push(assets[0]);

  const warmed = warmMarkdownDocument(assets.join("\n"));
  await vi.runAllTimersAsync();
  await warmed;

  expect(fetch).toHaveBeenCalledTimes(MARKDOWN_WARM_MAX_ASSETS);
});

test("direct warm requests retain only one pending idle source", async () => {
  vi.useFakeTimers();
  const first = warmMarkdownDocument("# first");
  const skipped = warmMarkdownDocument("# skipped");

  expect(vi.getTimerCount()).toBe(1);
  await skipped;
  await vi.runAllTimersAsync();
  await first;
});

test("reset releases pending warm state even when cancellation throws", async () => {
  let work!: IdleRequestCallback;
  vi.stubGlobal("requestIdleCallback", (callback: IdleRequestCallback) => {
    work = callback;
    return 1;
  });
  vi.stubGlobal("cancelIdleCallback", () => {
    throw new Error("scheduler unavailable");
  });
  const pending = warmMarkdownDocument("# pending");

  expect(() => resetMarkdownDocumentCache()).not.toThrow();
  await pending;
  work({} as IdleDeadline);

  // Cancellation released the single-flight slot and the late scheduler
  // callback cannot repopulate state from the invalidated generation.
  const next = warmMarkdownDocument("# next");
  expect(next).not.toBe(pending);
  resetMarkdownDocumentCache();
  await next;
});

test("a served figure reserves the size the server measured", () => {
  // The whole point of the exercise: the browser knows the shape of the box
  // before the picture is in it, so a document lays out once instead of
  // reflowing under the reader as each figure lands.
  const drawn = admittedHtml(640, 360);
  expect(drawn).toContain('width="640"');
  expect(drawn).toContain('height="360"');
  expect(drawn).toContain('alt="Plot"');
});

test("figures defer offscreen loading and decode asynchronously", () => {
  const drawn = admittedHtml(640, 360);
  expect(drawn).toContain('loading="lazy"');
  expect(drawn).toContain('decoding="async"');
  // Scheduling hints must not trade away the stable geometry that prevents
  // images arriving under the reader from moving the document.
  expect(drawn).toContain('width="640"');
  expect(drawn).toContain('height="360"');
});

test("an external figure is an explicit link and causes no image request", () => {
  const drawn = html("![Plot](https://example.com/plot.png)");
  expect(drawn).toContain('role="status"');
  expect(drawn).toContain('href="https://example.com/plot.png"');
  expect(drawn).not.toContain("<img");
});

test("forged or mismatched measured asset URLs cannot bless generic bytes", () => {
  for (const source of [
    `/leika-assets/${"a".repeat(64)}.png?w=1&h=1`,
    `/leika-assets/${"a".repeat(64)}-1x1.png?w=2&h=1`,
    `/leika-assets/not-a-digest-1x1.png?w=1&h=1`,
    `/leika-assets/${"a".repeat(64)}-1x1.too_long_suffix_name?w=1&h=1`,
  ]) {
    const drawn = html(`![Plot](${source})`);
    expect(drawn).toContain('role="status"');
    expect(drawn).not.toContain("<img");
  }
});

test("a controlled figure has one accessible expand control", () => {
  const drawn = interactiveAdmittedHtml(8, 8);
  const surface = matching(
    drawn,
    /<span\b[^>]*data-leika-inline-media[^>]*>.*?<\/span>/,
  );

  expect(surface).toMatch(/^<span\b[^>]*><img\b/);
  // Tailwind already makes the bare image block-level. Its phrasing span must
  // keep that flow while shrink-wrapping the button, or an image written
  // between words would move onto their line.
  expect(surface).toMatch(/class="[^"]*\bblock\b[^"]*\bw-fit\b/);
  expect(surface.match(/<button\b/g)).toHaveLength(1);
  expect(surface).toContain('aria-label="Expand image: Plot"');
});

test("a linked figure keeps link and expand as sibling actions", () => {
  const drawn = interactiveAdmittedHtml(8, 8, {
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
        admittedImage(8, 8),
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
