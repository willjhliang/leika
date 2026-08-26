type MarkdownImageObserver = Pick<
  IntersectionObserver,
  "disconnect" | "observe"
>;

type MarkdownImageObserverFactory = (
  callback: (
    entries: readonly Pick<IntersectionObserverEntry, "isIntersecting">[],
  ) => void,
  options: IntersectionObserverInit,
) => MarkdownImageObserver;

/** Track an image near its scroll frame, with enough margin to load ahead. */
export function observeMarkdownImageViewport(
  node: Element,
  onNearChange: (near: boolean) => void,
  createObserver: MarkdownImageObserverFactory = (callback, options) =>
    new IntersectionObserver((entries) => callback(entries), options),
): () => void {
  const observer = createObserver(
    (entries) => onNearChange(entries.some((entry) => entry.isIntersecting)),
    {
      root: node.closest('[data-slot="file-preview-reading-frame"]'),
      rootMargin: "800px 0px",
    },
  );
  observer.observe(node);
  return () => observer.disconnect();
}
