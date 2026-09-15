import { expect, test } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  ProgressiveMarkdownParser,
  type MarkdownPatch,
} from "./progressiveMarkdown";
import { PreviewMarkdownBlocks } from "./components/previewMarkdownBlocks";
import { renderMarkdown } from "./components/markdownDocument";

function drain(parser: ProgressiveMarkdownParser, patches: MarkdownPatch[]) {
  let count = 0;
  while (!patches.at(-1)?.complete && count++ < 2000)
    parser.accept({ type: "next" });
  expect(patches.at(-1)?.complete).toBe(true);
}

test("large documents emit bounded patches and wait for UI acknowledgement", () => {
  const source =
    "# First\n\n" + ("A readable paragraph. ".repeat(30) + "\n\n").repeat(500);
  const patches: MarkdownPatch[] = [];
  const parser = new ProgressiveMarkdownParser((patch) => patches.push(patch));
  parser.accept({ type: "source", source, complete: true, images: true });
  expect(patches).toHaveLength(1);
  expect(patches[0].renderedChars).toBeLessThan(source.length);
  parser.accept({ type: "source", source, complete: true, images: true });
  expect(patches).toHaveLength(1);
  drain(parser, patches);
  expect(
    new Set(patches.map((patch) => patch.renderedChars)).size,
  ).toBeGreaterThan(3);
  expect(patches.every((patch) => patch.blocks.length <= 96)).toBe(true);
  expect(
    patches
      .flatMap((patch) => patch.blocks)
      .filter((block) => block.index === 0),
  ).toHaveLength(1);
});

test("streaming keeps CommonMark semantics across incomplete constructs and forward references", () => {
  const source =
    "# Heading\n\n[forward][target]\n\n" +
    "- outer\n  - nested\n\n" +
    "| a | b |\n| - | - |\n| 1 | 2 |\n\n```md\n# not a heading\n```\n\n" +
    "<div>\n\nNested **text**.\n\n</div>\n\n# Heading\n\n[target]: https://example.com\n";
  const patches: MarkdownPatch[] = [];
  const blocks = new PreviewMarkdownBlocks(source.slice(0, 20));
  const parser = new ProgressiveMarkdownParser((patch) => {
    patches.push(patch);
    blocks.apply(patch);
  });
  for (let end = 24; end < source.length; end += 24) {
    parser.accept({
      type: "source",
      source: source.slice(0, end),
      complete: false,
      images: true,
    });
    for (let i = 0; i < 10; i++) parser.accept({ type: "next" });
  }
  parser.accept({ type: "source", source, complete: true, images: true });
  drain(parser, patches);
  expect(renderToStaticMarkup(blocks.document().element)).toBe(
    renderToStaticMarkup(renderMarkdown(source).element),
  );
  expect(blocks.document().headings).toEqual(renderMarkdown(source).headings);
});

test("late image preparation patches only affected blocks", () => {
  const raw = "# Heading\n\n![figure](figure.png)\n\nA stable paragraph.\n";
  const prepared = raw.replace(
    "figure.png",
    "/leika-assets/figure.png?w=600&h=400",
  );
  const patches: MarkdownPatch[] = [];
  const parser = new ProgressiveMarkdownParser((patch) => patches.push(patch));
  parser.accept({ type: "source", source: raw, complete: true, images: false });
  drain(parser, patches);
  const initialCount = patches.length;
  parser.accept({ type: "next" });
  parser.accept({
    type: "source",
    source: prepared,
    complete: true,
    images: true,
  });
  drain(parser, patches);
  const changed = patches.slice(initialCount).flatMap((patch) => patch.blocks);
  expect(changed).toHaveLength(1);
  expect(changed[0].signature).toContain('"tagName":"img"');
});
