import { ErrorBoundary } from "react-error-boundary";

import Markdown from "../Markdown";
import { GuiMarkdownMessage } from "../WebsocketMessages";

export default function MarkdownComponent({
  props: { _markdown: markdown },
}: GuiMarkdownMessage) {
  return (
    <ErrorBoundary
      fallback={<p className="text-center">Markdown failed to render</p>}
    >
      <Markdown>{markdown}</Markdown>
    </ErrorBoundary>
  );
}
