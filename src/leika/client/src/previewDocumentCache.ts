import type { RenderedDocument } from "./markdown";
import { MAX_GUI_MARKDOWN_SOURCE_BYTES } from "./guiLimits";

/** Decoded strings follow their Blob's lifetime, including its budget eviction. */
let decoded = new WeakMap<Blob, string>();
const documents = new Map<string, RenderedDocument>();
const MAX_DOCUMENTS = 8;
export const PREVIEW_DOCUMENT_CACHE_MAX_BYTES = 2 * 1024 * 1024;
let sourceBytes = 0;

export function cachedPreviewText(blob: Blob): string | null {
  return decoded.get(blob) ?? null;
}

export function rememberPreviewText(blob: Blob, text: string): void {
  if (blob.size <= MAX_GUI_MARKDOWN_SOURCE_BYTES) decoded.set(blob, text);
}

export function cachedPreviewDocument(source: string): RenderedDocument | null {
  const document = documents.get(source);
  if (document === undefined) return null;
  documents.delete(source);
  documents.set(source, document);
  return document;
}

/** Bound parsed previews separately from the Blob budget; long documents fit too. */
export function rememberPreviewDocument(
  source: string,
  document: RenderedDocument,
): void {
  const bytes = source.length * 2;
  if (bytes > PREVIEW_DOCUMENT_CACHE_MAX_BYTES) return;
  if (documents.delete(source)) sourceBytes -= bytes;
  documents.set(source, document);
  sourceBytes += bytes;
  while (
    documents.size > MAX_DOCUMENTS ||
    sourceBytes > PREVIEW_DOCUMENT_CACHE_MAX_BYTES
  ) {
    const oldest = documents.keys().next().value!;
    documents.delete(oldest);
    sourceBytes -= oldest.length * 2;
  }
}

export function resetPreviewDocumentCache(): void {
  decoded = new WeakMap();
  documents.clear();
  sourceBytes = 0;
}
