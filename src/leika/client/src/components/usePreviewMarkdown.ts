import * as React from "react";
import { FILE_PREVIEW_LEAD_CHARS } from "../filePreview";
import type { RenderedDocument } from "../markdown";
import type { MarkdownPatch } from "../progressiveMarkdown";
import MarkdownPreviewWorker from "../markdownPreviewWorker?worker&inline";
import { PreviewMarkdownBlocks } from "./previewMarkdownBlocks";

/** Keep one parser and one block tree alive as streamed text grows. */
export function usePreviewMarkdown(
  source: string | null,
  lead: string | null,
  continuityKey: string,
  complete = true,
  images = true,
): { document: RenderedDocument | null; error: string | null } {
  const initial = React.useMemo(
    () =>
      lead === null
        ? null
        : new PreviewMarkdownBlocks(lead.slice(0, FILE_PREVIEW_LEAD_CHARS)),
    [lead],
  );
  const initialDocument = React.useMemo(
    () => initial?.document() ?? null,
    [initial],
  );
  const [ready, setReady] = React.useState<{
    continuityKey: string;
    document: RenderedDocument;
    revision: number;
  } | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const activeWorker = React.useRef<Worker | null>(null);
  const hasSource = source !== null;
  // Initial content is only a seed. Stream updates must not recreate the worker.
  const initialRef = React.useRef(initial);
  initialRef.current = initial;
  React.useEffect(() => {
    setError(null);
    if (!hasSource) return;
    let active = true;
    let worker: Worker | undefined;
    const blocks = initialRef.current ?? new PreviewMarkdownBlocks(null);
    let revision = 0;
    const fail = () => {
      if (active)
        setError(
          "The Markdown preview could not be rendered. Download the file to read the rest.",
        );
      worker?.terminate();
    };
    try {
      worker = new MarkdownPreviewWorker();
      activeWorker.current = worker;
      worker.onmessage = (
        event: MessageEvent<MarkdownPatch | { error: string }>,
      ) => {
        if (!active) return;
        if ("error" in event.data) {
          fail();
          return;
        }
        try {
          const document = blocks.apply(event.data);
          revision += 1;
          React.startTransition(() =>
            setReady({ continuityKey, document, revision }),
          );
        } catch {
          fail();
        }
      };
      worker.onerror = fail;
    } catch {
      fail();
    }
    return () => {
      active = false;
      worker?.terminate();
      if (activeWorker.current === worker) activeWorker.current = null;
    };
  }, [continuityKey, hasSource]);

  React.useEffect(() => {
    if (source !== null)
      activeWorker.current?.postMessage({
        type: "source",
        source,
        complete,
        images,
      });
  }, [source, complete, images, continuityKey]);

  // The worker cannot queue another DOM batch until this one has committed.
  React.useEffect(() => {
    if (ready?.continuityKey !== continuityKey) return;
    const worker = activeWorker.current;
    const frame = requestAnimationFrame(() =>
      worker?.postMessage({ type: "next" }),
    );
    return () => cancelAnimationFrame(frame);
  }, [ready, continuityKey]);
  return {
    document:
      ready?.continuityKey === continuityKey ? ready.document : initialDocument,
    error,
  };
}
