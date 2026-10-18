import type * as React from "react";

import type { MediaSize } from "./mediaPreviewSize";

/** Every picture Leika draws: a plain `<img>`, decoded by the browser.
 *
 * Leika trusts its server, so a source goes straight to the browser, and one
 * it cannot decode shows the browser's own broken-image state. What a caller
 * may need back is the picture's natural size -- a media preview opens at it
 * -- which the browser knows once the picture has loaded.
 */
export function MediaImage({
  onSize,
  ...props
}: Omit<React.ComponentProps<"img">, "onLoad"> & {
  onSize?: (size: MediaSize) => void;
}) {
  return (
    <img
      {...props}
      onLoad={
        onSize &&
        ((event) =>
          onSize({
            width: event.currentTarget.naturalWidth,
            height: event.currentTarget.naturalHeight,
          }))
      }
    />
  );
}
