// How wide a media preview opens.
//
// Apart from the component that opens it, because it is a decision about a
// number and not about a popup: the same width is asked for by a pane's
// expand button, which has the picture in hand, and by a previewed file,
// which is still waiting for one. Kept here so both get the same answer.

import * as React from "react";

/** Below this, media is scaled up to fill the popup rather than opening as a
 * postage stamp in the middle of one. It is also what a preview opens at
 * before anything has said how big it should be. */
const FLOOR_PX = 880;

/** Everything the popup spends on itself: the margin it keeps from the edges
 * of the window, its own padding, and the title bar over the media. What is
 * left is what there is to show a picture in. The document frame next door
 * takes the same 6rem off, for the same reason. */
const CHROME_REM = 6;

/** What a picture's own dimensions are, once the browser has them. */
export interface MediaSize {
  width: number;
  height: number;
}

/** The width a media preview opens at.
 *
 * Media is the one thing a popup can take its size from rather than impose
 * one on: a picture was made at a size, and the preview is that size. Three
 * things can talk it down from that, and the smallest of them wins:
 *
 *   - the window's width, which a preview never exceeds;
 *   - the window's HEIGHT, converted through the picture's own aspect ratio.
 *     This is what a tall picture needs and a wide one never notices: without
 *     it the floor below would blow a portrait up past the bottom of the
 *     screen, and a preview you have to scroll to see the end of is not a
 *     preview;
 *   - the picture's own width, but never below the floor -- a thumbnail is
 *     scaled up to fill the popup instead of sitting in the middle of one.
 *
 * `null` is for media with no size to read: audio, which has none, and
 * anything the browser has not decoded yet.
 */
export function mediaPreviewWidth(size: MediaSize | null): string {
  // No aspect ratio to convert the height through, so there is nothing to
  // say but "as much as fits", and the floor is the guess.
  if (size === null) return `min(90vw, ${FLOOR_PX}px)`;
  const aspect = size.width / size.height;
  const wanted = Math.max(FLOOR_PX, size.width);
  return `min(90vw, calc((100dvh - ${CHROME_REM}rem) * ${aspect}), ${wanted}px)`;
}

/** A picture's own size, once the browser has decoded enough to know it.
 *
 * Null until then, and null again the moment the URL changes: a size left
 * over from the last image would open the preview wrong and then correct
 * itself, which is worse than opening at the floor and settling.
 *
 * This loads the same object URL the popup renders, which the browser already
 * has, so there is no second fetch to pay for.
 */
export function useMediaSize(url: string | null): MediaSize | null {
  const [size, setSize] = React.useState<MediaSize | null>(null);
  React.useEffect(() => {
    setSize(null);
    if (url === null) return;
    let active = true;
    const image = new window.Image();
    image.onload = () => {
      if (active) {
        setSize({ width: image.naturalWidth, height: image.naturalHeight });
      }
    };
    image.src = url;
    return () => {
      active = false;
      image.onload = null;
    };
  }, [url]);
  return size;
}
