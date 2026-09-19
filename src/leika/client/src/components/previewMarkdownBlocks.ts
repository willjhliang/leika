import * as React from "react";
import type { DocumentHeading, RenderedDocument } from "../markdown";
import {
  markdownBlocks,
  type MarkdownBlock,
  type MarkdownPatch,
} from "../progressiveMarkdown";
import { compileMarkdown } from "./markdownDocument";

type CompiledBlock = { signature: string; element: React.ReactElement };

/** Stable keyed fragments let React append blocks without replacing earlier DOM. */
export class PreviewMarkdownBlocks {
  private blocks: CompiledBlock[] = [];
  private headings: DocumentHeading[] = [];

  constructor(lead: string | null) {
    if (lead === null) return;
    const initial = markdownBlocks(lead, false);
    this.apply({
      type: "patch",
      ...initial,
      count: initial.blocks.length,
      renderedChars: lead.length,
      complete: false,
    });
  }

  apply(patch: MarkdownPatch): RenderedDocument {
    for (const block of patch.blocks) this.compile(block);
    if (patch.count !== undefined) this.blocks.length = patch.count;
    if (patch.headings !== undefined) this.headings = patch.headings;
    return this.document();
  }

  document(): RenderedDocument {
    return {
      element: React.createElement(
        React.Fragment,
        null,
        this.blocks.map((block) => block.element),
      ),
      headings: this.headings,
    };
  }

  private compile(block: MarkdownBlock): void {
    if (this.blocks[block.index]?.signature === block.signature) return;
    const result = compileMarkdown({
      tree: { type: "root", children: [block.node] },
      headings: [],
    });
    this.blocks[block.index] = {
      signature: block.signature,
      element: React.cloneElement(result.element, {
        key: `block-${block.index}`,
      }),
    };
  }
}
