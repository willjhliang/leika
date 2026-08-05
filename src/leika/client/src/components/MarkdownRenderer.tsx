import React from "react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { createMarkdownRenderer, type MarkdownComponents } from "../markdown";

// How the document's elements are drawn. The pipeline in `../markdown` decides
// what a document *contains*; everything here decides what it looks like in a
// panel row or a preview dialog.
//
// Body copy sets no size of its own: it is whatever the surface showing the
// document asked for -- 13px in a panel row, where prose sits among inputs and
// has to line up with them, and larger in a preview dialog, where the document
// is the only thing on screen. Every other size here is written in `em`
// against that one, so a whole document scales from a single number and its
// proportions never depend on where it landed.
//
// Spacing works one way throughout: a block owns the room above it and none
// below it. The gap between any two blocks is then a single value rather than
// the sum of one block's bottom and the next one's top, a document never ends
// on a margin, and nothing needs to know what follows it. `not-first:` is what
// makes that safe -- the opening block sits flush with the top of whatever is
// showing it, a panel row or a preview dialog.
const BLOCK_GAP = "not-first:mt-4";
/** The wider gap, for the two blocks that mark a break rather than continue
 * the text: a heading and a rule. */
const BREAK_GAP = "not-first:mt-6";

// Leading is set once, on the document, and inherited by everything in it --
// paragraphs, list items, table cells, quotes alike. Set per-element instead,
// every element anyone forgot falls back to the leading of the *surrounding
// UI*, which is set for single-line labels beside inputs: a list would read
// tighter than the paragraph above it for no reason a reader could see. 1.5 is
// GitHub's, and headings override it below.
const DOCUMENT_CLASS = "leading-[1.5]";

function MdText(props: React.ComponentPropsWithoutRef<"p">) {
  return <p className={BLOCK_GAP} {...props} />;
}

function MdAnchor(props: React.ComponentPropsWithoutRef<"a">) {
  return (
    <a
      className="font-medium underline underline-offset-4"
      rel="noreferrer"
      {...props}
    />
  );
}

// A heading takes more room above it than below: the space over one belongs
// to the break it makes from what came before, while the text under it is
// what it names and reads as part of it. One value for every level -- the
// break a heading makes is the same break whatever its rank, and the
// descending sizes already say which is which.
// The tighter leading is GitHub's too: a heading is short and large, and the
// body's spacing would pull its own two lines apart.
const HEADING_CLASS = `${BREAK_GAP} scroll-m-20 leading-[1.25] font-semibold tracking-tight`;
// GitHub's heading scale, which is the one the rest of this renderer is
// aiming at, and multiples of the body rather than sizes: a heading is a
// proportion of the text it names, so it grows with it instead of being a
// fixed jump that reads differently at each size.
const HEADING_SIZE = {
  h1: "text-[2em]",
  h2: "text-[1.5em]",
  h3: "text-[1.25em]",
  h4: "text-[1em]",
  h5: "text-[0.875em]",
  h6: "text-[0.85em]",
} as const;

function mdHeading(tag: keyof typeof HEADING_SIZE) {
  const Heading = (props: React.ComponentPropsWithoutRef<"h1">) => {
    const Tag = tag;
    return (
      <Tag {...props} className={`${HEADING_CLASS} ${HEADING_SIZE[tag]}`} />
    );
  };
  Heading.displayName = `Md${tag.toUpperCase()}`;
  return Heading;
}

function mdList(tag: "ol" | "ul") {
  const List = ({
    className,
    ...props
  }: React.ComponentPropsWithoutRef<"ul">) => {
    const Tag = tag;
    const marker =
      className === "contains-task-list"
        ? "list-none"
        : tag === "ol"
          ? "list-decimal"
          : "list-disc";
    return <Tag {...props} className={`${BLOCK_GAP} ml-6 ${marker}`} />;
  };
  List.displayName = tag === "ol" ? "MdOrderedList" : "MdList";
  return List;
}

// One component for both forms of code, told apart by the `block` prop the
// pipeline sets on the `<code>` inside a `<pre>`. `pre` then renders only its
// children, since the block form draws its own.
//
// Set at 0.9em rather than the body's own size, as GitHub sets it: a
// monospaced face at the same nominal size reads a size larger than the prose
// around it, and an inline span of it would otherwise sit in a sentence like a
// heading.
function MdCode({
  block,
  children,
  ...props
}: React.ComponentPropsWithoutRef<"code"> & { block?: boolean }) {
  return block ? (
    <pre
      className={`${BLOCK_GAP} overflow-x-auto rounded-lg bg-muted p-4 text-[0.9em]`}
    >
      <code {...props}>{children}</code>
    </pre>
  ) : (
    <code
      className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.9em]"
      {...props}
    >
      {children}
    </code>
  );
}

// The panel's table, which sizes itself for a panel. A table in a document is
// part of the document: it reads at the size the prose around it does, and it
// is spaced like any other block. The gap goes on a wrapper because `Table`
// draws a scroll container of its own around the `<table>`, and it is the
// outermost element that is the document's block.
function MdTable(props: React.ComponentPropsWithoutRef<"table">) {
  return (
    <div className={BLOCK_GAP}>
      <Table className="text-[1em]" {...props} />
    </div>
  );
}

// A rule is a break in the document, so it is spaced like the other one.
function MdRule(props: React.ComponentPropsWithoutRef<"hr">) {
  return <hr className={`${BREAK_GAP} border-t`} {...props} />;
}

function MdImage(props: React.ComponentPropsWithoutRef<"img">) {
  return <img className="mx-auto max-w-60 rounded-lg" {...props} />;
}

const components: MarkdownComponents = {
  p: MdText,
  a: MdAnchor,
  h1: mdHeading("h1"),
  h2: mdHeading("h2"),
  h3: mdHeading("h3"),
  h4: mdHeading("h4"),
  h5: mdHeading("h5"),
  h6: mdHeading("h6"),
  ul: mdList("ul"),
  ol: mdList("ol"),
  // Items sit closer together than blocks do -- a list is one thing, and the
  // gap only has to separate its lines from each other. In `em`, so it holds
  // whatever the leading around it works out to.
  li: (props) => <li className="not-first:mt-[0.25em]" {...props} />,
  code: MdCode,
  pre: (props) => <>{props.children}</>,
  blockquote: (props) => (
    <blockquote className={`${BLOCK_GAP} border-l-2 pl-4 italic`} {...props} />
  ),
  hr: MdRule,
  // Inline HTML the sanitizer keeps and GitHub authors reach for: a
  // collapsed section is a block of the document like any other.
  details: (props) => <details className={BLOCK_GAP} {...props} />,
  table: MdTable,
  thead: TableHeader,
  tbody: TableBody,
  tr: TableRow,
  th: TableHead,
  td: TableCell,
  img: MdImage,
};

const render = createMarkdownRenderer(components);

/**
 * Draw a markdown document, the way GitHub would.
 *
 * Rendering is synchronous and total: a document is a pure function of its
 * source, so it lands in the same paint as everything around it, and there is
 * no failure case to fall back from -- every string is a valid document.
 *
 * The element around it is the document itself, and holds what belongs to the
 * whole of one rather than to any tag in it. What a surface passes in -- the
 * text size -- is inherited through it; what the document decides for itself
 * -- its leading -- is set on it.
 */
export function MarkdownRenderer(props: { children?: string }) {
  const source = props.children ?? "";
  const document = React.useMemo(() => render(source), [source]);
  return <div className={DOCUMENT_CLASS}>{document}</div>;
}
