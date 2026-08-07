/**
 * The renderer's memory: the same document must be the same tree.
 *
 * What the pipeline produces is pinned in `markdown.test.ts`; here it is only
 * the remembering -- identity across calls is what lets a reopened preview
 * skip the parse, and what lets React leave the DOM alone when a press's
 * fresh copy turns out to match what warming already showed.
 */

import { expect, test } from "vitest";

import { renderMarkdown } from "./markdownDocument";

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
