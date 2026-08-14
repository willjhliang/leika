/**
 * What a markdown document is allowed to contain, and what it renders to.
 *
 * These pin the pipeline against GitHub rather than against a snapshot of
 * itself: each case is a thing an author can write in a README, and the
 * assertion is that Leika shows what GitHub shows. The styling that sits on
 * top lives in the e2e suite, which has a browser to measure it in.
 */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";

import {
  contentsOf,
  createMarkdownRenderer,
  DOCUMENT_ID_PREFIX,
} from "./markdown";
import {
  AdmittedMarkdownImage,
  MarkdownImage,
  MarkdownLink,
  MarkdownPicture,
} from "./components/MarkdownMedia";
import {
  inspectMarkdownImageSource,
  MARKDOWN_RESERVED_MAX_DIMENSION,
  MARKDOWN_RESERVED_MAX_PIXELS,
} from "./components/markdownMediaSafety";

/** Unstyled, so the assertions read as HTML rather than as Tailwind. */
const render = createMarkdownRenderer({});

const html = (markdown: string) =>
  renderToStaticMarkup(render(markdown).element);
const productionMediaRender = createMarkdownRenderer({
  a: MarkdownLink,
  img: MarkdownImage,
  picture: MarkdownPicture,
});
const productionMediaHtml = (markdown: string) =>
  renderToStaticMarkup(productionMediaRender(markdown).element);
const measuredAsset = (width: number, height: number) =>
  `/leika-assets/${"a".repeat(64)}-${width}x${height}.png?w=${width}&h=${height}`;

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

  test("an image the server registered keeps its URL", () => {
    // Path-backed previews arrive naming `/leika-assets/...` URLs rather
    // than carrying image bytes; a relative URL passes sanitation the same
    // way it does on GitHub.
    expect(html("![plot](/leika-assets/abc123.png)")).toContain(
      'src="/leika-assets/abc123.png"',
    );
  });

  test("a responsive picture keeps source and image as direct children", () => {
    const out = html(
      '<picture><source srcset="/wide.png 2x" src="/not-for-pictures.png" type="image/png" sizes="100vw" media="(min-width: 40rem)"><img src="/fallback.png" alt="Plot"></picture>',
    );
    const matched = out.match(/<picture>.*?<\/picture>/);
    expect(matched).not.toBeNull();
    const picture = matched![0];

    // A picture only participates in source selection when its source nodes
    // and fallback image remain its own children. A component that wraps every
    // image independently would leave valid React but invalid picture HTML.
    expect(picture).toMatch(
      /^<picture><source\b[^>]*\/><img\b[^>]*\/><\/picture>$/,
    );
    expect(picture).toMatch(/<source\b[^>]*srcset=/i);
    expect(picture).toContain('media="(min-width: 40rem)"');
    expect(picture).toContain('src="/fallback.png"');
    expect(picture).toContain('alt="Plot"');
    // GitHub's picture allowlist is deliberately narrower than the browser's
    // source element: these do not become an accidental second media surface.
    expect(picture).not.toContain("/not-for-pictures.png");
    expect(picture).not.toContain("type=");
    expect(picture).not.toContain("sizes=");
  });

  test("video and audio HTML do not become playable document content", () => {
    const out = html(
      '<video src="/movie.mp4" controls><source src="/movie.webm" type="video/webm">Video fallback</video>' +
        '<audio src="/sound.mp3" controls>Audio fallback</audio>',
    );

    // File previews can show these formats, but the Markdown allowlist does
    // not. Pin that boundary so adding a React component cannot silently make
    // untrusted document HTML start fetching or playing media.
    expect(out).not.toMatch(/<(?:video|audio)\b/);
    expect(out).toContain("Video fallback");
    expect(out).toContain("Audio fallback");
  });

  test("a linked image remains the link's direct noninteractive content", () => {
    const out = html("[![Plot](/plot.png)](https://example.com/report)");
    const link = out.match(/<a\b[^>]*>.*<\/a>/)?.[0];

    expect(link).toMatch(/^<a\b[^>]*><img\b[^>]*\/><\/a>$/);
    expect(link).not.toContain("<button");
  });

  test("author rel attributes cannot remove safe external-link isolation", () => {
    const ordinary = productionMediaHtml(
      '<a href="https://example.com" target="_blank" rel="author">report</a>',
    );
    const image = renderToStaticMarkup(
      createElement(AdmittedMarkdownImage, {
        alt: "Plot",
        linkedBy: {
          href: "https://example.com",
          rel: "author",
          target: "_blank",
        },
        measured: { width: 8, height: 8 },
        sourceKind: "asset",
        src: measuredAsset(8, 8),
      }),
    );
    for (const out of [ordinary, image]) {
      const rel = /<a\b[^>]*\brel="([^"]+)"/.exec(out)?.[1].split(" ");
      expect(rel).toEqual(expect.arrayContaining(["noreferrer", "noopener"]));
      // The sanitizer may discard the author's token; either way it cannot
      // replace the two isolation tokens forced by the production component.
      expect(rel).toHaveLength(new Set(rel).size);
    }
  });

  test("only sane measured asset dimensions reserve an image box", () => {
    const validWidth = MARKDOWN_RESERVED_MAX_DIMENSION;
    const validHeight = MARKDOWN_RESERVED_MAX_PIXELS / validWidth;
    const validSource = measuredAsset(validWidth, validHeight);
    expect(inspectMarkdownImageSource(validSource)).toEqual({
      admission: {
        ok: true,
        size: { width: validWidth, height: validHeight },
      },
      sourceKind: "asset",
    });
    const valid = renderToStaticMarkup(
      createElement(AdmittedMarkdownImage, {
        alt: "plot",
        measured: { width: validWidth, height: validHeight },
        sourceKind: "asset",
        src: validSource,
      }),
    );
    expect(valid).toContain(`width="${validWidth}"`);
    expect(valid).toContain(`height="${validHeight}"`);
    expect(valid).toContain('loading="lazy"');

    for (const source of [
      `/leika-assets/${"a".repeat(64)}.png?w=1&h=1`,
      `/leika-assets/${"a".repeat(64)}-1x1.png?w=2&h=1`,
      `/leika-assets/${"a".repeat(64)}-${MARKDOWN_RESERVED_MAX_DIMENSION + 1}x1.png?w=${MARKDOWN_RESERVED_MAX_DIMENSION + 1}&h=1`,
      `/leika-assets/${"a".repeat(64)}-${validWidth}x${validHeight + 1}.png?w=${validWidth}&h=${validHeight + 1}`,
      `/leika-assets/${"a".repeat(64)}-${"9".repeat(400)}x1.png?w=${"9".repeat(400)}&h=1`,
    ]) {
      expect(inspectMarkdownImageSource(source).admission.ok).toBe(false);
      const out = productionMediaHtml(`![plot](${source})`);
      expect(out).not.toMatch(/\bwidth=/);
      expect(out).not.toMatch(/\bheight=/);
      expect(out).not.toContain('loading="lazy"');
      expect(out).not.toContain("<img");
    }
  });

  test("a large inlined image survives whole, and as its own", () => {
    // Long data URLs are lifted out of the source before parsing and put
    // back after -- an inlined image is megabytes the parser would otherwise
    // read as markdown. The swap has to be invisible: each image keeps its
    // own bytes, in markdown syntax and in inline HTML alike.
    const first = `data:image/png;base64,${"A".repeat(2000)}`;
    const second = `data:image/jpeg;base64,${"B".repeat(2000)}`;
    const out = html(`![one](${first})\n\n<img alt="two" src="${second}">`);
    expect(out).toContain(`src="${first}" alt="one"`);
    expect(out).toContain(`alt="two" src="${second}"`);
  });

  test("a long data URL in a code block is text, and stays text", () => {
    // The lift is an inversion, not an image feature: a URL that was written
    // as writing comes back as the writing it was.
    const url = `data:image/png;base64,${"C".repeat(2000)}`;
    expect(html("```\n" + url + "\n```")).toContain(url);
  });

  test("embed stand-ins cannot collide with authored text or URLs", () => {
    const embedded = `data:image/png;base64,${"D".repeat(2000)}`;
    // This is the first namespace/index the lifter would otherwise choose.
    // It appears both as prose and in a sanitizer-allowed image source, so a
    // post-sanitize global restoration must leave both authored values alone.
    const literal = "data:,leika-embed-0:0";
    const legacyLiteral = "data:,leika-embed-0";
    const out = html(
      `![embedded](${embedded})\n\n\`${literal}\` ${legacyLiteral}\n\n` +
        `<img alt="literal" src="${literal}">`,
    );

    expect(out).toContain(`src="${embedded}" alt="embedded"`);
    expect(out).toContain(`<code>${literal}</code>`);
    expect(out).toContain(legacyLiteral);
    expect(out).toContain(`alt="literal" src="${literal}"`);
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

describe("what a document says it contains", () => {
  const headings = (markdown: string) => render(markdown).headings;

  test("a heading is listed by the link that reaches it", () => {
    // The fragment, not the id: a contents entry has to be an ordinary
    // in-document link, or it would need its own way of being followed.
    expect(headings("# Setup\n\n## Running it")).toEqual([
      { fragment: "setup", level: 1, text: "Setup" },
      { fragment: "running-it", level: 2, text: "Running it" },
    ]);
  });

  test("a heading with markup in it reads as its words", () => {
    expect(headings("## The `--seed` flag")[0]).toMatchObject({
      text: "The --seed flag",
      fragment: "the---seed-flag",
    });
    expect(headings("## A [link](https://x.test) in a heading")[0].text).toBe(
      "A link in a heading",
    );
  });

  test("a heading written as HTML is listed like any other", () => {
    // By the time these are collected the two are one tree, which is the
    // reason to collect them there and not from the markdown source.
    expect(headings('<h2 id="mine">Written by hand</h2>')).toEqual([
      { fragment: "mine", level: 2, text: "Written by hand" },
    ]);
  });

  test("what cannot be linked to is not listed", () => {
    // Nothing to show for a name, and nothing a `#` could reach.
    expect(headings("## \n\ntext")).toEqual([]);
    expect(headings("Just prose.")).toEqual([]);
  });

  test("the same document lists the same headings its page carries", () => {
    // The property the whole thing rests on: every entry names an id that is
    // really on the page, since both come out of the one pass.
    const source = "# Setup\n\n## Running it\n\n### Café\n";
    const page = html(source);
    for (const heading of headings(source)) {
      expect(page).toContain(`id="${DOCUMENT_ID_PREFIX}${heading.fragment}"`);
    }
  });
});

describe("contentsOf", () => {
  const of = (markdown: string) =>
    contentsOf(render(markdown).headings).map((heading) => heading.text);

  test("handles more headings than JavaScript's call argument limit", () => {
    const headings = Array.from({ length: 150_000 }, (_, index) => ({
      fragment: `section-${index}`,
      level: index === 0 ? 1 : 2,
      text: `Section ${index}`,
    }));
    expect(contentsOf(headings)).toHaveLength(headings.length);
  });

  test("keeps three levels, counted from the shallowest one there is", () => {
    // A file written with `##` at its top level is not a document whose
    // contents are all subsections, so the depth is relative rather than
    // measured from `h1`.
    expect(of("## A\n\n### B\n\n#### C\n\n##### D")).toEqual(["A", "B", "C"]);
    expect(of("# A\n\n## B\n\n### C\n\n#### D")).toEqual(["A", "B", "C"]);
  });

  test("is nothing at all when there is no list to be made", () => {
    // One entry is the document's title said a second time, and no entry is
    // a file with no headings. Neither is worth a column.
    expect(of("# Just a title\n\ntext")).toEqual([]);
    expect(of("Prose with no headings.")).toEqual([]);
    // Deep headings under a single shallow one do count, once there are two.
    expect(of("# Title\n\n## First\n\n## Second")).toEqual([
      "Title",
      "First",
      "Second",
    ]);
  });

  test("counts only the headings it would show towards being a list", () => {
    // Two headings, but one of them is too deep to be listed -- so what is
    // left is a list of one, which is not a list.
    expect(of("# Title\n\n##### Aside")).toEqual([]);
  });
});
