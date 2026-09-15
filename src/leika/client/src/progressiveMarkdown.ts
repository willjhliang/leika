import type { RootContent } from "hast";
import { parseMarkdown, type DocumentHeading } from "./markdown";
import { MAX_GUI_MARKDOWN_SOURCE_BYTES } from "./guiLimits";

export type MarkdownStreamInput =
  | { type: "source"; source: string; complete: boolean; images: boolean }
  | { type: "next" };
export interface MarkdownBlock {
  index: number;
  node: RootContent;
  signature: string;
  images: boolean;
}
export interface MarkdownPatch {
  type: "patch";
  blocks: MarkdownBlock[];
  count?: number;
  headings?: DocumentHeading[];
  renderedChars: number;
  complete: boolean;
  /** Exact fully prepared source for a reusable completed document. */
  source?: string;
}

/** Positions change when image URLs are rewritten, but the visible blocks do not. */
export function markdownBlocks(source: string, images: boolean) {
  const parsed = parseMarkdown(source);
  const blocks = parsed.tree.children.map((node, index): MarkdownBlock => {
    const json = JSON.stringify(node, (key, value) =>
      key === "position" ? undefined : value,
    );
    const hasImage = json.includes('"tagName":"img"');
    return {
      index,
      node: JSON.parse(json) as RootContent,
      signature: (hasImage && images ? "images:" : "text:") + json,
      images,
    };
  });
  return { blocks, headings: parsed.headings };
}

/** Parse growing documents off-thread and send only changed/new blocks.
 *
 * CommonMark references and open tables/lists can change earlier syntax, so
 * each stage uses the real whole-document parser. Doubling the parse window
 * bounds aggregate parsing to less than three full parses, rather than
 * reparsing an ever-growing prefix for every network chunk. Unchanged blocks
 * keep their identity. UI acknowledgements bound outstanding DOM work.
 */
export class ProgressiveMarkdownParser {
  private desired: Extract<MarkdownStreamInput, { type: "source" }> | null =
    null;
  private renderedSource = "";
  private renderedImages = false;
  private renderedComplete = false;
  private signatures: string[] = [];
  private pending: MarkdownPatch[] = [];
  private waiting = false;

  constructor(private readonly publish: (patch: MarkdownPatch) => void) {}

  accept(message: MarkdownStreamInput): void {
    if (message.type === "source") {
      if (message.source.length > MAX_GUI_MARKDOWN_SOURCE_BYTES)
        throw new Error("Markdown render limit exceeded");
      this.desired = message;
    } else {
      this.waiting = false;
    }
    this.pump();
  }

  private pump(): void {
    if (this.waiting || this.desired === null) return;
    if (this.pending.length === 0) {
      const { source, images, complete } = this.desired;
      if (
        source === this.renderedSource &&
        images === this.renderedImages &&
        complete === this.renderedComplete
      )
        return;
      const extending =
        !this.renderedComplete ||
        (images === this.renderedImages &&
          source.startsWith(this.renderedSource));
      // Slow or tiny network chunks must not trigger quadratic reparsing.
      // The final chunk always flushes the remaining partial window.
      const nextWindow = Math.max(16 * 1024, this.renderedSource.length * 2);
      if (
        extending &&
        this.renderedSource.length > 0 &&
        !complete &&
        source.length < nextWindow
      )
        return;
      const target = extending
        ? Math.min(source.length, nextWindow)
        : source.length;
      const prefix = source.slice(0, target);
      const parsed = markdownBlocks(prefix, images);
      const changed = parsed.blocks.filter(
        (block) => this.signatures[block.index] !== block.signature,
      );
      const done = complete && target === source.length;
      // A patch is a small commit, even when the worker has the whole file.
      for (let offset = 0; offset < changed.length; offset += 96) {
        this.pending.push({
          type: "patch",
          blocks: changed.slice(offset, offset + 96),
          renderedChars: target,
          complete: false,
        });
      }
      if (this.pending.length === 0)
        this.pending.push({
          type: "patch",
          blocks: [],
          renderedChars: target,
          complete: false,
        });
      Object.assign(this.pending[this.pending.length - 1], {
        count: parsed.blocks.length,
        headings: parsed.headings,
        complete: done,
        source: done && images ? source : undefined,
      });
      this.signatures = parsed.blocks.map((block) => block.signature);
      this.renderedSource = prefix;
      this.renderedImages = images;
      this.renderedComplete = done;
    }
    this.waiting = true;
    this.publish(this.pending.shift()!);
  }
}
