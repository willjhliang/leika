import React from "react";
import * as runtime from "react/jsx-runtime";
import * as provider from "@mdx-js/react";
import { evaluate } from "@mdx-js/mdx";
import { type MDXComponents } from "mdx/types";
import { ReactNode, useEffect, useState } from "react";
import remarkGfm from "remark-gfm";
import rehypeColorChips from "rehype-color-chips";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { visit } from "unist-util-visit";
import { Transformer } from "unified";
import { Root } from "hast";

// Custom Rehype to clean up code blocks (the renderer needs normalized block markup)
// Adds "block" to any code non-inline code block, which gets directly passed into
// the code renderer.
function rehypeCodeblock(): void | Transformer<Root, Root> {
  return (tree) => {
    visit(tree, "element", (node, _i, parent) => {
      if (node.tagName !== "code") return;
      if (parent && parent.type === "element" && parent.tagName === "pre") {
        node.properties = { block: true, ...node.properties };
      }
    });
  };
}

// Renderers for the HTML that MDX emits.
//
// Body copy is 14px: the browser default (16px) is too large next to GUI
// inputs, and the 12px used by the inputs themselves is too cramped to read
// as prose. Headings keep a descending scale so they still read as headings.
function MdxText(props: React.ComponentPropsWithoutRef<"p">) {
  return <p className="text-sm leading-6 not-first:mt-4" {...props} />;
}

function MdxAnchor(props: React.ComponentPropsWithoutRef<"a">) {
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
// what it names and reads as part of it. Paragraphs are 4 apart, so anything
// less than that above a heading would have grouped it with the wrong side.
// One value for every level -- the break a heading makes is the same break
// whatever its rank, and the descending sizes already say which is which.
// `first:mt-0` keeps a document that opens with a heading flush with the top
// of whatever is showing it -- a panel row or a preview dialog.
const HEADING_CLASS =
  "mt-6 scroll-m-20 font-semibold tracking-tight first:mt-0";
const HEADING_SIZE = {
  h1: "text-3xl",
  h2: "text-2xl",
  h3: "text-xl",
  h4: "text-base",
  h5: "text-base",
  h6: "text-base",
} as const;

function mdxHeading(tag: keyof typeof HEADING_SIZE) {
  const Heading = (props: React.ComponentPropsWithoutRef<"h1">) => {
    const Tag = tag;
    return (
      <Tag {...props} className={`${HEADING_CLASS} ${HEADING_SIZE[tag]}`} />
    );
  };
  Heading.displayName = `Mdx${tag.toUpperCase()}`;
  return Heading;
}

function mdxList(tag: "ol" | "ul") {
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
    return <Tag {...props} className={`my-4 ml-6 ${marker}`} />;
  };
  List.displayName = tag === "ol" ? "MdxOrderedList" : "MdxList";
  return List;
}

function MdxCode({
  block,
  children,
  ...props
}: React.ComponentPropsWithoutRef<"code"> & { block?: boolean }) {
  return block ? (
    <pre className="my-4 overflow-x-auto rounded-lg bg-muted p-4 text-sm">
      <code {...props}>{children}</code>
    </pre>
  ) : (
    <code
      className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm"
      {...props}
    >
      {children}
    </code>
  );
}

function MdxCite(props: React.ComponentPropsWithoutRef<"cite">) {
  return (
    <cite
      className="mt-2 block overflow-hidden text-ellipsis text-sm text-muted-foreground"
      {...props}
    />
  );
}

function MdxImage(props: React.ComponentPropsWithoutRef<"img">) {
  return <img className="mx-auto max-w-60 rounded-lg" {...props} />;
}

const components: MDXComponents = {
  p: MdxText,
  a: MdxAnchor,
  h1: mdxHeading("h1"),
  h2: mdxHeading("h2"),
  h3: mdxHeading("h3"),
  h4: mdxHeading("h4"),
  h5: mdxHeading("h5"),
  h6: mdxHeading("h6"),
  ul: mdxList("ul"),
  ol: mdxList("ol"),
  li: (props) => <li className="mt-2" {...props} />,
  code: MdxCode,
  pre: (props) => <>{props.children}</>,
  blockquote: (props) => (
    <blockquote className="my-4 border-l-2 pl-4 italic" {...props} />
  ),
  Cite: MdxCite,
  table: Table,
  thead: TableHeader,
  tbody: TableBody,
  tr: TableRow,
  th: TableHead,
  td: TableCell,
  img: MdxImage,
  // Anything else MDX might emit (raw JSX elements) renders as nothing.
  "*": () => <></>,
};

async function parseMarkdown(markdown: string) {
  // @ts-ignore (necessary since JSX runtime isn't properly typed according to the internet)
  const { default: Content } = await evaluate(markdown, {
    ...runtime,
    ...provider,
    development: false,
    remarkPlugins: [remarkGfm],
    rehypePlugins: [rehypeCodeblock, rehypeColorChips],
  });
  return Content;
}

/**
 * Parses and renders markdown on the client. This is generally a bad practice.
 * NOTE: Only run on markdown you trust.
 * It might be worth looking into sandboxing all markdown so that it can't run JS.
 */
export function MarkdownRenderer(props: { children?: string }) {
  const [child, setChild] = useState<ReactNode>(null);

  useEffect(() => {
    // Guard against stale/after-unmount updates: parseMarkdown is async, so a
    // slow earlier parse could otherwise resolve last and render stale content,
    // or call setChild after unmount. The promise also rejects asynchronously,
    // so the error fallback must live in `.catch`, not the synchronous `try`.
    let cancelled = false;
    parseMarkdown(props.children ?? "")
      .then((Content) => {
        if (cancelled) return;
        setChild(<Content components={components} />);
      })
      .catch(() => {
        if (cancelled) return;
        setChild(
          <h2 className="text-2xl font-semibold tracking-tight">
            Error Parsing Markdown...
          </h2>,
        );
      });
    return () => {
      cancelled = true;
    };
  }, [props.children]);

  return child;
}
