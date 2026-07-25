import { ErrorBoundary } from "react-error-boundary";

import Markdown from "../Markdown";
import { GuiMarkdownMessage } from "../WebsocketMessages";

export default function MarkdownComponent({
  props: { visible, _markdown: markdown },
}: GuiMarkdownMessage) {
  if (!visible) return null;
  return (
    <ErrorBoundary
      fallback={<p className="text-center">Markdown failed to render</p>}
    >
      <Markdown>{markdown}</Markdown>
    </ErrorBoundary>
  );
}
