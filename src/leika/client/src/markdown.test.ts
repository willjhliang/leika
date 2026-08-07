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

import { createMarkdownRenderer, DOCUMENT_ID_PREFIX } from "./markdown";

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

describe("links from one part of a document to another", () => {
  test("a heading answers to the name GitHub gives it", () => {
    // A contents list is written against the slugs GitHub derives, so these
    // are the same ones -- punctuation dropped, spaces kept as the gaps they
    // were, which is why two hyphens come out of "W24 / W25".
    expect(html("## W24 / W25")).toContain(
      `<h2 id="${DOCUMENT_ID_PREFIX}w24--w25">`,
    );
  });

  test("a repeated heading is still a heading of its own", () => {
    const out = html("# Setup\n\n# Setup");
    expect(out).toContain(`id="${DOCUMENT_ID_PREFIX}setup"`);
    expect(out).toContain(`id="${DOCUMENT_ID_PREFIX}setup-1"`);
  });

  test("every id a document names is namespaced, its own included", () => {
    // The rule the renderer relies on to resolve a link: an id on the page is
    // the prefix plus what the document asked for, and nothing else is. It
    // holds for ids an author writes by hand, and for the ones the footnote
    // machinery writes -- which arrive already prefixed and are prefixed
    // again, so that their links, prefixed once, still find them.
    expect(html('<h2 id="mine">x</h2>')).toContain(
      `id="${DOCUMENT_ID_PREFIX}mine"`,
    );
    // The form a log written for GitHub uses to give a section a short name
    // of its own, rather than the slug its whole title comes to.
    expect(
      html('<a id="w24-w25"></a>\n\n## W24/W25: the mixture ratio'),
    ).toContain(`id="${DOCUMENT_ID_PREFIX}w24-w25"`);
    const footnote = html("text[^1]\n\n[^1]: note");
    const [, href] = /href="#([^"]+)"/.exec(footnote) ?? [];
    expect(footnote).toContain(`id="${DOCUMENT_ID_PREFIX}${href}"`);
  });
});

describe("what a document is drawn as", () => {
  test("code reaches the page as the tags a stylesheet can find", () => {
    // Nothing marks a fenced block any more. typeset tells one from an inline
    // span the way CSS does, by the parent, so the tree stays plain HTML and
    // the renderer has no opinion about code to hold.
    expect(html("```\nx\n```")).toBe("<pre><code>x\n</code></pre>");
    expect(html("`x`")).toBe("<p><code>x</code></p>");
  });
});
