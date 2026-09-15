import {
  ProgressiveMarkdownParser,
  type MarkdownStreamInput,
} from "./progressiveMarkdown";

const parser = new ProgressiveMarkdownParser((patch) =>
  self.postMessage(patch),
);
self.onmessage = (event: MessageEvent<MarkdownStreamInput>) => {
  try {
    parser.accept(event.data);
  } catch {
    self.postMessage({ error: "The Markdown preview could not be rendered." });
  }
};
