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

import type { Nodes, Root } from "hast";
import type { ReactElement } from "react";
import * as runtime from "react/jsx-runtime";
import rehypeColorChips from "rehype-color-chips";
import rehypeRaw from "rehype-raw";
import rehypeReact, { type Options as RehypeReactOptions } from "rehype-react";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import { unified } from "unified";

/** How a tag name maps to the component that draws it. */
export type MarkdownComponents = RehypeReactOptions["components"];

/**
 * What every id a document names is prefixed with once it is on the page.
 *
 * An id is global to the page, so a document that could name one freely could
 * take over an id the app is already using -- `#search`, `#title` -- and quietly
 * redirect a label or an `aria-describedby` that Leika wrote. Sanitation's
 * answer, GitHub's too, is to leave the ids in place but move all of them into
 * a namespace of their own, so a document can only ever collide with itself.
 *
 * The prefix is applied to ids and not to the `href`s that point at them, so a
 * link written `#setup` lands on `#user-content-setup`: the same rewrite, done
 * once, is what following a link in a document has to undo. That is the whole
 * reason this is a name rather than a literal in the schema.
 */
export const DOCUMENT_ID_PREFIX = "user-content-";

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
  clobberPrefix: DOCUMENT_ID_PREFIX,
  protocols: {
    ...defaultSchema.protocols,
    src: [...(defaultSchema.protocols?.src ?? []), "data"],
  },
};

/**
 * Length past which a `data:` URL is taken out of the source before parsing.
 *
 * An embedded image is megabytes of base64 sitting in the middle of a
 * document, and the parser reads every byte of it as markdown: a file whose
 * text parses in a quarter second takes several seconds once its images are
 * inlined (`add_preview_button` inlines them on the way here, `image_root`
 * before that). None of that reading can change anything -- base64 has no
 * markup in it -- so each long URL is swapped for a short numbered stand-in
 * (`data:,leika-embed-0:3`) on the way in and swapped back on the way out,
 * and the parser only ever sees the document's actual writing.
 *
 * The swap is a pure inversion, not an image feature: it is undone wherever
 * the stand-in comes to rest, so a long URL an author put in a code block
 * comes back as the text it was, the same as one in an `src`. The threshold
 * just keeps the machinery off the tiny URLs that cost nothing to parse.
 */
const EMBED_MIN_LENGTH = 1024;

const EMBED_URL_NAMESPACE_PREFIX = "data:,leika-embed-";
const EMBED_URL_NAMESPACE = /data:,leika-embed-(\d+):/g;

/** Choose a namespace that occurs nowhere in the authored source.
 *
 * Collecting all numeric namespaces in one pass avoids an attacker-controlled
 * series of whole-source `includes()` scans. If the chosen prefix occurred,
 * its number would necessarily be in `used`, so the search is collision-free
 * rather than merely improbable. */
function unusedEmbedPrefix(source: string): string {
  const used = new Set<string>();
  for (const match of source.matchAll(EMBED_URL_NAMESPACE)) used.add(match[1]);
  let namespace = 0;
  while (used.has(String(namespace))) namespace += 1;
  return `${EMBED_URL_NAMESPACE_PREFIX}${namespace}:`;
}

/** Swap every long `data:` URL for a numbered stand-in, keeping the originals.
 *
 * The character class is where a URL can end in any syntax that can hold one:
 * whitespace, a markdown destination's `)`, an HTML attribute's quote, a tag's
 * `>`, a code span's backtick. Everything between is carried whole, so the
 * inverse is a straight substitution.
 */
function liftEmbeds(source: string): {
  lifted: string;
  embeds: string[];
  embedPrefix: string;
} {
  const embeds: string[] = [];
  const embedPrefix = unusedEmbedPrefix(source);
  const lifted = source.replace(
    new RegExp(`data:[^\\s)"'\`<>]{${EMBED_MIN_LENGTH},}`, "g"),
    (url) => {
      embeds.push(url);
      return `${embedPrefix}${embeds.length - 1}`;
    },
  );
  return { lifted, embeds, embedPrefix };
}

/** Put the lifted URLs back, wherever their stand-ins ended up.
 *
 * Runs after sanitation, and safely so: a protocol is all sanitation reads of
 * a URL, and a stand-in keeps the `data:` of what it stands for. An attribute
 * that may not hold a `data:` URL is dropped with the stand-in still in it,
 * and there is nothing left to restore.
 */
function rehypeRestoreEmbeds() {
  return (
    tree: Root,
    file: { data: { embeds?: string[]; embedPrefix?: string } },
  ) => {
    const embeds = file.data.embeds ?? [];
    const embedPrefix = file.data.embedPrefix;
    if (embeds.length === 0 || embedPrefix === undefined) return;
    const standInPattern = new RegExp(`${embedPrefix}(\\d+)`, "g");
    const restore = (value: string): string =>
      value.replace(standInPattern, (standIn, index) => {
        return embeds[Number(index)] ?? standIn;
      });
    const visit = (node: Nodes): void => {
      if (node.type === "text" && node.value.includes(embedPrefix)) {
        node.value = restore(node.value);
      }
      if (node.type === "element") {
        for (const [name, value] of Object.entries(node.properties)) {
          if (typeof value === "string" && value.includes(embedPrefix)) {
            node.properties[name] = restore(value);
          }
        }
      }
      if ("children" in node) node.children.forEach(visit);
    };
    visit(tree);
  };
}

/** One heading, as a contents list needs it. */
export interface DocumentHeading {
  /** What a link to this heading is written as, without the `#`.
   *
   * The id off the page less {@link DOCUMENT_ID_PREFIX} -- which is to say,
   * exactly what an author writing a link to their own heading would put.
   * Stored that way so a contents entry is an ordinary in-document link and
   * is followed by the same code that follows one written in the file.
   */
  fragment: string;
  /** 1 for `#`, 6 for `######`. What a contents list indents by. */
  level: number;
  /** The heading as it reads: its text, with any markup in it flattened. */
  text: string;
}

const HEADING_TAGS = new Set(["h1", "h2", "h3", "h4", "h5", "h6"]);

/** Take down the document's headings as it is rendered.
 *
 * Here rather than in a pass of its own so that there is one parse and one
 * set of ids. A contents list is only usable if every entry points at a
 * heading that exists under exactly that name, and the way to guarantee that
 * is to read the names off the tree the page is about to be built from --
 * after slugging, after sanitation's rename, after a heading written as
 * inline HTML has become a heading like any other.
 *
 * Left out rather than listed dead: a heading with no id, one whose id did not
 * come from the rename above -- no link written with a `#` could reach it --
 * and one with nothing to show for a name.
 */
function rehypeCollectHeadings() {
  return (tree: Root, file: { data: { headings?: DocumentHeading[] } }) => {
    const headings: DocumentHeading[] = [];
    const textOf = (node: Nodes): string =>
      node.type === "text"
        ? node.value
        : "children" in node
          ? node.children.map(textOf).join("")
          : "";
    const visit = (node: Nodes): void => {
      if (node.type === "element" && HEADING_TAGS.has(node.tagName)) {
        const id = node.properties.id;
        const text = textOf(node).trim();
        if (
          typeof id === "string" &&
          id.startsWith(DOCUMENT_ID_PREFIX) &&
          text !== ""
        ) {
          headings.push({
            fragment: id.slice(DOCUMENT_ID_PREFIX.length),
            level: Number(node.tagName.slice(1)),
            text,
          });
        }
        // A heading holds no headings; nothing below it to walk.
        return;
      }
      if ("children" in node) node.children.forEach(visit);
    };
    visit(tree);
    file.data.headings = headings;
  };
}

/** How many levels below the shallowest heading a contents list goes.
 *
 * Three levels in all. A contents list is for finding the part of a document
 * you want, and past three levels it stops being a list of parts and becomes
 * the document again, in outline. Counted from the shallowest heading present
 * rather than from `h1`, because plenty of files are written with `##` as
 * their top level -- and one written that way is not a document whose
 * contents are all subsections. */
const CONTENTS_DEPTH = 2;

/** The entries a contents list shows, out of everything a document heads.
 *
 * Fewer than two is not a list: one entry is the document's own title said
 * twice, and none is a file with no headings at all. Both give nothing back.
 */
export function contentsOf(headings: DocumentHeading[]): DocumentHeading[] {
  if (headings.length === 0) return [];
  let shallowest = Number.POSITIVE_INFINITY;
  for (const heading of headings) {
    shallowest = Math.min(shallowest, heading.level);
  }
  const listed = headings.filter(
    (heading) => heading.level <= shallowest + CONTENTS_DEPTH,
  );
  return listed.length < 2 ? [] : listed;
}

/** A rendered document: the tree to draw, and what is in it. */
export interface RenderedDocument {
  element: ReactElement;
  headings: DocumentHeading[];
}

/**
 * Build a renderer that turns markdown into React elements.
 *
 * The pipeline is ordered by what each step is allowed to assume:
 * `remark-rehype` passes inline HTML through as raw text, `rehype-raw` parses
 * it into real elements, and only then does sanitation run -- on a tree where
 * every element is visible to it. Leika's own pass comes last, so the marks it
 * adds are not mistaken for an author's and stripped.
 *
 * Slugs are the exception, and run *before* sanitation on purpose. A heading's
 * id is the document's name for one of its own parts, which is exactly what
 * sanitation namespaces (`DOCUMENT_ID_PREFIX`); an id that skipped the rewrite
 * would be the one thing in a document able to reach the page around it.
 * Running here also means a heading written as inline HTML is given an id on
 * the same terms as one written with hashes, since by now they are one tree.
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
    .use(rehypeSlug)
    .use(rehypeSanitize, schema)
    .use(rehypeRestoreEmbeds)
    .use(rehypeColorChips)
    .use(rehypeCollectHeadings)
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

  return (markdown: string): RenderedDocument => {
    const { lifted, embeds, embedPrefix } = liftEmbeds(markdown);
    const file = processor.processSync({
      value: lifted,
      data: { embeds, embedPrefix },
    });
    return {
      element: file.result,
      headings: (file.data as { headings?: DocumentHeading[] }).headings ?? [],
    };
  };
}
