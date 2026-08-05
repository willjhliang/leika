/**
 * Markdown, rendered the way GitHub renders it.
 *
 * A document is prose, not a program. Leika used to hand markdown to MDX,
 * which reads the same text as source code: `{...}` is a JavaScript
 * expression, `<br>` is an unterminated JSX tag, and either one is a *parse
 * error* that fails the whole document rather than a character that shows up
 * in it. Authors do not write files for a compiler -- they write them for
 * GitHub, then point Leika at the same file and expect the same page.
 *
 * So this is a plain CommonMark pipeline: remark parses, GFM adds the tables,
 * strikethrough, task lists and autolinks that GitHub adds, and the small
 * subset of inline HTML that GitHub keeps is kept here too. Nothing in a
 * document is evaluated, which is why a preview can be opened on a file
 * whether or not you wrote it.
 *
 * Two properties follow, and both are worth relying on:
 *
 *   - **No document fails.** CommonMark has no syntax errors -- every string
 *     of characters is a valid document, and anything that is not markup is
 *     text. There is no parse-failure state left to render.
 *   - **Rendering is synchronous.** Nothing has to be compiled, so a document
 *     is a pure function of its source and appears in the first paint rather
 *     than one tick later.
 */

import type { Root } from "hast";
import type { ReactElement } from "react";
import * as runtime from "react/jsx-runtime";
import rehypeColorChips from "rehype-color-chips";
import rehypeRaw from "rehype-raw";
import rehypeReact, { type Options as RehypeReactOptions } from "rehype-react";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import { unified, type Transformer } from "unified";
import { visit } from "unist-util-visit";

/** How a tag name maps to the component that draws it. */
export type MarkdownComponents = RehypeReactOptions["components"];

/**
 * GitHub's allowlist, plus the one protocol Leika needs on top of it.
 *
 * `defaultSchema` is hast-util-sanitize's transcription of what GitHub keeps
 * when it renders a README: the tags and attributes an author can reach for,
 * and nothing that can run. Sanitizing is what makes inline HTML safe to
 * support at all -- `<br>` and `<sub>` work, `<script>` and `onclick` are
 * dropped, and a document from anywhere can be shown without asking where it
 * came from.
 *
 * The addition is `data:` image sources. Leika inlines local images into the
 * document before it leaves Python (`add_text`'s `image_root`), where GitHub
 * -- which serves images through a proxy of its own -- has no reason to allow
 * that protocol. Without this line, every image Leika resolves would be
 * stripped from the page it was resolved for.
 */
const schema = {
  ...defaultSchema,
  protocols: {
    ...defaultSchema.protocols,
    src: [...(defaultSchema.protocols?.src ?? []), "data"],
  },
};

/**
 * Mark the `<code>` inside a `<pre>` so one component can draw both forms.
 *
 * Markdown gives a fenced block and an inline span the same tag name and
 * distinguishes them only by the parent, which a React component never sees.
 * Flattening that into a prop lets `code` own the difference instead of
 * splitting it across two renderers that have to agree.
 */
function rehypeCodeBlock(): void | Transformer<Root, Root> {
  return (tree) => {
    visit(tree, "element", (node, _index, parent) => {
      if (node.tagName !== "code") return;
      if (parent && parent.type === "element" && parent.tagName === "pre") {
        node.properties = { block: true, ...node.properties };
      }
    });
  };
}

/**
 * Build a renderer that turns markdown into React elements.
 *
 * The pipeline is ordered by what each step is allowed to assume:
 * `remark-rehype` passes inline HTML through as raw text, `rehype-raw` parses
 * it into real elements, and only then does sanitation run -- on a tree where
 * every element is visible to it. Leika's own passes come last, so the marks
 * and styles they add are not mistaken for an author's and stripped.
 *
 * The processor is built once and reused: it holds no per-document state, and
 * assembling a unified pipeline is far more work than running one.
 */
export function createMarkdownRenderer(components: MarkdownComponents) {
  const processor = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkRehype, { allowDangerousHtml: true })
    .use(rehypeRaw)
    .use(rehypeSanitize, schema)
    .use(rehypeColorChips)
    .use(rehypeCodeBlock)
    .use(rehypeReact, {
      // React's own jsx-runtime types and the ones rehype-react asks for
      // describe the same three functions with different signatures, so the
      // handoff is asserted rather than inferred. There is nothing to get
      // wrong here beyond passing the wrong runtime.
      Fragment: runtime.Fragment,
      jsx: runtime.jsx,
      jsxs: runtime.jsxs,
      components,
    } as RehypeReactOptions);

  return (markdown: string): ReactElement =>
    processor.processSync(markdown).result;
}
