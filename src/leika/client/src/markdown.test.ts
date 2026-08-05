/**
 * What a markdown document is allowed to contain, and what it renders to.
 *
 * These pin the pipeline against GitHub rather than against a snapshot of
 * itself: each case is a thing an author can write in a README, and the
 * assertion is that Leika shows what GitHub shows. The styling that sits on
 * top lives in the e2e suite, which has a browser to measure it in.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";

import { createMarkdownRenderer } from "./markdown";

/** Unstyled, so the assertions read as HTML rather than as Tailwind. */
const render = createMarkdownRenderer({});

const html = (markdown: string) => renderToStaticMarkup(render(markdown));

describe("what a document may contain", () => {
  test("braces are characters, not expressions", () => {
    // MDX read these as JavaScript and failed the whole document over them.
    // They are ordinary text in every path a shell or a set can be written:
    expect(html("runs/shift{3,6} and {3.0, 6.0}")).toContain(
      "runs/shift{3,6} and {3.0, 6.0}",
    );
  });

  test("a void tag written unclosed is a line break, not an error", () => {
    // `<br>` is how tables get a second line, and how everyone writes it.
    expect(html("one<br>two")).toBe("<p>one<br/>two</p>");
  });

  test("inline HTML GitHub keeps is kept", () => {
    expect(html("H<sub>2</sub>O")).toBe("<p>H<sub>2</sub>O</p>");
    expect(html("<details><summary>more</summary>text</details>")).toContain(
      "<summary>more</summary>",
    );
  });

  test("inline HTML GitHub drops is dropped", () => {
    // Sanitation is what makes inline HTML safe to support at all, and it is
    // why a preview can be opened on a file you did not write.
    expect(html("<script>alert(1)</script>")).not.toContain("alert");
    expect(html("<img src=x onerror=alert(1)>")).not.toContain("onerror");
    expect(html('<a href="javascript:alert(1)">x</a>')).not.toContain(
      "javascript:",
    );
  });

  test("images Leika inlined for the document survive it", () => {
    // `add_text(image_root=...)` resolves local images to data URLs before
    // the document leaves Python; GitHub's own schema has no reason to allow
    // that protocol, so dropping it would strip every resolved image.
    expect(html("![a](data:image/png;base64,AAAA)")).toContain(
      'src="data:image/png;base64,AAAA"',
    );
  });

  test("no document fails to render", () => {
    // CommonMark has no syntax errors: anything that is not markup is text.
    for (const source of ["", "<", "{", "```", "|a|\n|-", "<div", "*[x"]) {
      expect(() => html(source)).not.toThrow();
    }
  });
});

describe("GitHub-flavored markdown", () => {
  test("tables become tables", () => {
    const out = html("| a | b |\n|---|---|\n| 1 | 2 |");
    expect(out).toContain("<table>");
    expect(out).toContain("<td>1</td>");
  });

  test("strikethrough, task lists and autolinks", () => {
    expect(html("~~gone~~")).toContain("<del>gone</del>");
    expect(html("- [x] done")).toContain('type="checkbox"');
    expect(html("https://example.com")).toContain('href="https://example.com"');
  });
});

describe("how code reaches its component", () => {
  test("a fenced block is marked, an inline span is not", () => {
    // Markdown gives both the same tag name and tells them apart only by the
    // parent, which a React component never sees.
    const marked = createMarkdownRenderer({
      code: (props: { block?: boolean; children?: unknown }) =>
        (props.block ? "BLOCK" : "INLINE") as never,
    });
    expect(renderToStaticMarkup(marked("```\nx\n```"))).toContain("BLOCK");
    expect(renderToStaticMarkup(marked("`x`"))).toContain("INLINE");
  });
});
