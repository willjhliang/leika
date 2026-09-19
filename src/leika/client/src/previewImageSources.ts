import { createContext } from "react";

/** Image updates belong to one text stream, never to a global filename. */
export const PreviewImageSourcesContext = createContext<
  { sources?: ReadonlyMap<string, string>; pending: boolean } | undefined
>(undefined);

/** Match Markdown's escaped spaces/Unicode without changing filesystem identity. */
export function previewImageSourceKey(source: string): string {
  return new URL(source, "http://leika.invalid/").href;
}
