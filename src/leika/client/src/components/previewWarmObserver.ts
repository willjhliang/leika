type PreviewWarmObserver = Pick<IntersectionObserver, "disconnect" | "observe">;
type PreviewWarmObserverFactory = (
  callback: (
    entries: readonly Pick<IntersectionObserverEntry, "isIntersecting">[],
  ) => void,
) => PreviewWarmObserver;

/** Start the one-shot preview prefetch observer used by enabled buttons. */
export function startPreviewWarmObservation(
  enabled: boolean,
  node: Element | null,
  uuid: string,
  send: (message: { type: "GuiPreviewWarmMessage"; uuid: string }) => void,
  createObserver: PreviewWarmObserverFactory = (callback) =>
    new IntersectionObserver((entries) => callback(entries)),
): () => void {
  if (!enabled || node === null) return () => {};
  let observer: PreviewWarmObserver | null = null;
  let sent = false;
  observer = createObserver((entries) => {
    if (sent || !entries.some((entry) => entry.isIntersecting)) return;
    sent = true;
    if (observer === null) return;
    observer.disconnect();
    send({ type: "GuiPreviewWarmMessage", uuid });
  });
  observer.observe(node);
  return () => observer.disconnect();
}
