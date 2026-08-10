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
import { expect, test } from "vitest";

import { renderMarkdown } from "./markdownDocument";
import { MarkdownMediaController } from "./MarkdownMedia";

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

test("a served figure reserves the size the server measured", () => {
  // The whole point of the exercise: the browser knows the shape of the box
  // before the picture is in it, so a document lays out once instead of
  // reflowing under the reader as each figure lands.
  const drawn = html("![Plot](/leika-assets/abc.png?w=640&h=360)");
  expect(drawn).toContain('width="640"');
  expect(drawn).toContain('height="360"');
  expect(drawn).toContain('alt="Plot"');
});

test("figures defer offscreen loading and request atomic presentation", () => {
  const drawn = html("![Plot](/leika-assets/abc.png?w=640&h=360)");
  expect(drawn).toContain('loading="lazy"');
  expect(drawn).toContain('decoding="sync"');
  // Scheduling hints must not trade away the stable geometry that prevents
  // images arriving under the reader from moving the document.
  expect(drawn).toContain('width="640"');
  expect(drawn).toContain('height="360"');
});

test("a figure with no measurement is left as it was", () => {
  // An image from anywhere else, or one whose header declared no size: the
  // browser discovers it on arrival, which is what it always did.
  const drawn = html("![Plot](https://example.com/plot.png)");
  expect(drawn).not.toContain("width=");
  expect(drawn).not.toContain("height=");
  expect(drawn).not.toContain('loading="lazy"');
  expect(drawn).not.toContain("decoding=");
});

test("external declared geometry keeps its eager loading behavior", () => {
  const drawn = html("![Plot](https://example.com/plot.png?w=640&h=360)");
  expect(drawn).toContain('width="640"');
  expect(drawn).toContain('height="360"');
  expect(drawn).not.toContain('loading="lazy"');
  expect(drawn).not.toContain("decoding=");
});

test("a controlled figure has one accessible expand control", () => {
  const drawn = interactiveHtml("![Plot](/plot.png)");
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
  const drawn = interactiveHtml(
    "[![Plot](/plot.png)](https://example.com/report)",
  );
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

test("a controlled picture keeps its selection tree and has no button", () => {
  const drawn = interactiveHtml(
    '<picture><source srcset="/wide.png 2x"><img src="/plot.png" alt="Plot"></picture>',
  );
  const picture = matching(drawn, /<picture>.*?<\/picture>/);

  expect(picture).toMatch(
    /^<picture><source\b[^>]*\/><img\b[^>]*\/><\/picture>$/,
  );
  expect(drawn).not.toContain("data-leika-inline-media");
  expect(drawn).not.toContain("<button");
});

test("a caption under a figure is still markdown", () => {
  // Why the size travels in the URL rather than in an `<img>` written into
  // the document: a tag on a line of its own opens an HTML block, and
  // everything down to the next blank line stops being parsed.
  const drawn = html("![Plot](/leika-assets/abc.png?w=8&h=8)\n*Figure 1*");
  expect(drawn).toContain("<em>Figure 1</em>");
});
