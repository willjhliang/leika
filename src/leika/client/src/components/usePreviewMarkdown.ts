import * as React from "react";
import { flushSync } from "react-dom";
import { FILE_PREVIEW_LEAD_CHARS } from "../filePreview";
import type { RenderedDocument } from "../markdown";
import type { MarkdownPatch } from "../progressiveMarkdown";
import MarkdownPreviewWorker from "../markdownPreviewWorker?worker&inline";
import { PreviewMarkdownBlocks } from "./previewMarkdownBlocks";
import {
  cachedMarkdownDocument,
  rememberMarkdownDocument,
} from "./markdownDocument";

/** Keep one parser and one block tree alive as streamed text grows. */
export function usePreviewMarkdown(
  source: string | null,
  lead: string | null,
  continuityKey: string,
  complete = true,
  images = true,
): {
  document: RenderedDocument | null;
  error: string | null;
  finishMounting: () => void;
} {
  const cached = React.useMemo(
    () =>
      source !== null && complete && images
        ? cachedMarkdownDocument(source)
        : null,
    [source, complete, images],
  );
  // A cached parse still costs DOM work. Mount its first blocks before filling
  // the rest, using the same small batches as the worker. Refreshes keep the
  // complete old document so they cannot shrink an existing scroll range.
  const openedWith = React.useRef(cached);
  const [cachedCount, setCachedCount] = React.useState(96);
  const cachedBlocks =
    cached !== null &&
    cached === openedWith.current &&
    React.isValidElement<{ children?: React.ReactNode[] }>(cached.element) &&
    Array.isArray(cached.element.props.children)
      ? cached.element.props.children
      : null;
  const moreCached = cachedBlocks !== null && cachedCount < cachedBlocks.length;
  React.useEffect(() => {
    if (!moreCached) return;
    const frame = requestAnimationFrame(() =>
      setCachedCount((count) => count + 96),
    );
    return () => cancelAnimationFrame(frame);
  }, [moreCached, cachedCount]);
  const mountedCached = React.useMemo(
    () =>
      cached !== null && cachedBlocks !== null && moreCached
        ? {
            ...cached,
            element: React.createElement(
              React.Fragment,
              null,
              cachedBlocks.slice(0, cachedCount),
            ),
          }
        : cached,
    [cached, cachedBlocks, moreCached, cachedCount],
  );
  const finishMounting = React.useCallback(() => {
    // An anchor may name a block not yet mounted. Complete before the reader's
    // normal click handler looks up its target, preserving navigation semantics.
    if (moreCached) flushSync(() => setCachedCount(Infinity));
  }, [moreCached]);
  const hasCached = cached !== null;
  const previousCached = React.useRef<{
    continuityKey: string;
    document: RenderedDocument;
  } | null>(null);
  if (cached !== null)
    previousCached.current = { continuityKey, document: cached };
  const initial = React.useMemo(
    () =>
      lead === null || hasCached
        ? null
        : new PreviewMarkdownBlocks(lead.slice(0, FILE_PREVIEW_LEAD_CHARS)),
    [lead, hasCached],
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
    if (!hasSource || hasCached) return;
    let active = true;
    let worker: Worker | undefined;
    const blocks = initialRef.current ?? new PreviewMarkdownBlocks(null);
    let revision = 0;
    let pendingFrame = 0;
    const replacingCache =
      previousCached.current?.continuityKey === continuityKey;
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
          if (event.data.complete && event.data.source !== undefined) {
            rememberMarkdownDocument(event.data.source, document);
          }
          if (replacingCache && !event.data.complete) {
            // A replacement worker starts without the old block tree. Keep
            // the complete cached view while it builds, so its partial prefix
            // cannot collapse the reader's scroll range during refresh.
            pendingFrame = requestAnimationFrame(() =>
              worker?.postMessage({ type: "next" }),
            );
            return;
          }
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
      cancelAnimationFrame(pendingFrame);
      worker?.terminate();
      if (activeWorker.current === worker) activeWorker.current = null;
    };
  }, [continuityKey, hasSource, hasCached]);

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
      mountedCached ??
      (ready?.continuityKey === continuityKey
        ? ready.document
        : previousCached.current?.continuityKey === continuityKey
          ? previousCached.current.document
          : initialDocument),
    error,
    finishMounting,
  };
}
