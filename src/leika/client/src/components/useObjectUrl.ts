import * as React from "react";

/** An object URL for `data`, revoked when `data` is replaced or the owner
 * unmounts.
 *
 * The URL never passes through `null` between two sources, so an element that
 * keeps showing it -- a streamed pane's `<img>` -- keeps its last picture
 * until the browser has loaded the next one. Revoking a URL the browser has
 * already loaded does not take its pixels off the screen.
 */
export function useObjectUrl(
  data: BlobPart | null,
  type: string,
): string | null {
  const [url, setUrl] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (data === null) {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(new Blob([data], { type }));
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [data, type]);
  return url;
}
