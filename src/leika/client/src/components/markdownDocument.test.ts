/**
 * The renderer's memory, and the one thing its components add to a document.
 *
 * What the pipeline produces is pinned in `markdown.test.ts`; here it is the
 * remembering -- identity across calls is what lets a reopened preview skip
 * the parse, and what lets React leave the DOM alone when a press's fresh
 * copy turns out to match what warming already showed -- and the size a
 * served figure reserves before it arrives.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import { renderMarkdown } from "./markdownDocument";

const html = (markdown: string) =>
  renderToStaticMarkup(renderMarkdown(markdown).element);

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

test("a figure with no measurement is left as it was", () => {
  // An image from anywhere else, or one whose header declared no size: the
  // browser discovers it on arrival, which is what it always did.
  const drawn = html("![Plot](https://example.com/plot.png)");
  expect(drawn).not.toContain("width=");
  expect(drawn).not.toContain("height=");
});

test("a caption under a figure is still markdown", () => {
  // Why the size travels in the URL rather than in an `<img>` written into
  // the document: a tag on a line of its own opens an HTML block, and
  // everything down to the next blank line stops being parsed.
  const drawn = html("![Plot](/leika-assets/abc.png?w=8&h=8)\n*Figure 1*");
  expect(drawn).toContain("<em>Figure 1</em>");
});
