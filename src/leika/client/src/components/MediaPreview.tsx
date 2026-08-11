import { Maximize2Icon, MaximizeIcon, MinimizeIcon } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { HintTooltip } from "./common";
import { guiLabelClassName } from "./guiLabelStyles";
import {
  PREVIEW_FULLSCREEN_ATTR,
  usePreviewFullscreen,
} from "./previewFullscreen";

/** The control that opens a media element's preview.
 *
 * Still called "expand" on its face, because that is what pressing it does to
 * the picture already in front of you. {@link MediaPreview} is what it opens.
 *
 * Chrome for the media, not part of it: revealed on hover. Keyboard focus and
 * coarse pointers (which never hover) reveal it too, so it is never
 * unreachable. Hovering is watched through `group/media`, so the positioned
 * ancestor must carry `group/media relative` -- see {@link MediaSurface},
 * which is the only thing that should be rendering this.
 */
function ExpandButton({
  subject,
  accessibleLabel,
  onExpand,
}: {
  /** What is being expanded, lowercase: completes "Expand ___". */
  subject: string;
  /** A more specific name for repeated controls. The tooltip deliberately
   * stays short; this is only what assistive technology uses to distinguish
   * one otherwise-identical corner from the next. */
  accessibleLabel?: string;
  onExpand: () => void;
}) {
  const label = `Expand ${subject}`;
  return (
    <HintTooltip hint={label}>
      <Button
        type="button"
        variant="secondary"
        size="icon-sm"
        // A 24px square, matching the height of a GUI row's controls.
        // `icon-sm` is 28px and there is no 24px icon variant between it and
        // `icon-xs`, which would also shrink the 14px glyph.
        // Bottom-right, because the top of a media element is where titles
        // and legends usually sit.
        className="absolute right-2 bottom-2 size-6 opacity-0 group-hover/media:opacity-100 focus-visible:opacity-100 pointer-coarse:opacity-100"
        onClick={onExpand}
        aria-label={accessibleLabel ?? label}
      >
        <Maximize2Icon />
      </Button>
    </HintTooltip>
  );
}

/** The same media chrome, on a phrasing host suitable for a document.
 *
 * A Markdown image ordinarily lives inside a paragraph (and can itself be
 * inside a link), where {@link MediaSurface}'s `div` is invalid. The span is
 * only a positioned, shrink-wrapped surface for the corner button; it does
 * not give the image a size or ask it to load. Keeping this explicit rather
 * than making MediaSurface polymorphic also keeps refs honest at both call
 * sites. Its block flow is deliberate: Tailwind's base rule already makes a
 * bare image block-level, so an inline wrapper would pull an image written
 * between words onto their line and change the document it was added to.
 */
export function InlineMediaSurface({
  subject,
  accessibleLabel,
  className,
  ref,
  onExpand,
  children,
}: {
  subject: string;
  accessibleLabel?: string;
  className?: string;
  ref?: React.Ref<HTMLSpanElement>;
  onExpand?: () => void;
  children: React.ReactNode;
}) {
  return (
    <span
      ref={ref}
      className={cn("group/media relative block w-fit max-w-full", className)}
      data-leika-inline-media
    >
      {children}
      {onExpand === undefined ? null : (
        <ExpandButton
          subject={subject}
          accessibleLabel={accessibleLabel}
          onExpand={onExpand}
        />
      )}
    </span>
  );
}

/** A media element together with its expand affordance.
 *
 * Owns the `group/media` the button's hover reveal keys off, so no caller has
 * to remember it. `onExpand` is optional: the copy inside the preview renders
 * through here too, and must not offer to expand itself again.
 */
export function MediaSurface({
  subject,
  className,
  ref,
  onExpand,
  children,
}: {
  subject: string;
  className?: string;
  /** The surface is the media's measurable box, so callers that size
   * themselves from it observe this element rather than a nested one. */
  ref?: React.Ref<HTMLDivElement>;
  onExpand?: () => void;
  children: React.ReactNode;
}) {
  return (
    <div ref={ref} className={cn("group/media relative", className)}>
      {children}
      {onExpand === undefined ? null : (
        <ExpandButton subject={subject} onExpand={onExpand} />
      )}
    </div>
  );
}

/** The corner control that gives a preview the whole window, and takes it
 * back.
 *
 * Its own place in the row of corner chrome: after the download, before the
 * close. Left to right that is what to do WITH the file, what to do with the
 * popup, and how to leave -- and leaving stays where it has always been,
 * under the pointer that reaches for the far corner without looking.
 */
function FullscreenCorner({
  fullscreen,
  onToggle,
}: {
  fullscreen: boolean;
  onToggle: () => void;
}) {
  const label = fullscreen ? "Exit full window" : "Fill the window";
  return (
    <HintTooltip hint={label}>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="absolute top-2 right-10"
        onClick={onToggle}
        aria-label={label}
        aria-pressed={fullscreen}
        data-leika-preview-fullscreen
      >
        {fullscreen ? <MinimizeIcon /> : <MaximizeIcon />}
      </Button>
    </HintTooltip>
  );
}

/** A piece of media, shown at its own size.
 *
 * The one popup media opens in, whether it was expanded from a pane or sent
 * by the server as a file to look at. Both are the same act -- something with
 * a size of its own, given the room to be seen at it -- and they were drawn
 * two different ways for long enough to drift: one sized to its picture, the
 * other fitting the picture into a frame it had picked in advance, which left
 * a portrait image marooned between two columns of empty dialog.
 *
 * So there is no frame here. The popup is the width its caller asks for --
 * `mediaPreviewWidth` in ./mediaPreviewSize -- and the media fills it.
 *
 * Unless it has been given the whole window, which is the one size a caller
 * does not get a say in: full-window is the reader's answer to "this is too
 * small", and a width computed from the media is exactly what they were
 * disagreeing with. That answer outlives the popup it was given in -- see
 * ./previewFullscreen -- and `rememberAs` is what it is kept against.
 *
 * `title` is drawn, always. It is the one line of chrome a preview has, and
 * what it says is which of the things on the page you are now looking at --
 * a question the media itself cannot answer, since it looks the same here as
 * it did in the panel. Media with no label of its own names its own kind, the
 * way an unlabelled image says "Image".
 *
 * Focus is handled as a viewer, not as a form. On open it lands on the frame
 * itself rather than the first button in it: a viewer's tabbable elements are
 * chrome (download, close), some of them tooltipped, and focusing one of those
 * under keyboard modality pops its tooltip open -- which then swallows the
 * Escape meant for the dialog, since Escape closes the innermost open thing
 * first. On close, focus is left alone: closing a viewer means "done reading",
 * and sending focus back to the button that opened it draws a focus ring (and,
 * from Escape, that button's tooltip) that nobody asked for.
 */
export function MediaPreview({
  open,
  onOpenChange,
  title,
  rememberAs,
  width,
  height,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Names what is being previewed, so that "fill the window" is remembered
   * for this one and not for the next. A file's name, or the uuid of the pane
   * whose media this is. */
  rememberAs: string;
  /** CSS width for the dialog. Defaults to the stock 4xl content width. */
  width?: string;
  /** CSS height for the dialog. Left out, the popup is as tall as what it
   * holds. Given, the contents take the room that is left instead -- which is
   * what something that scrolls needs, since it has no height of its own to
   * be asked for. */
  height?: string;
  children: React.ReactNode;
}) {
  const popupRef = React.useRef<HTMLDivElement | null>(null);
  const [fullscreen, setFullscreen] = usePreviewFullscreen(rememberAs);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        ref={popupRef}
        initialFocus={popupRef}
        finalFocus={false}
        // A preview can be almost a viewport of Markdown above live Plotly
        // canvases. Fading/scaling that surface and sampling those canvases
        // through a backdrop filter makes the underlying layers part of each
        // opening frame. The viewer is deliberately opaque from frame one.
        presentation="viewer"
        // A branch, not a pile of overrides. Both halves reach the element
        // through `cn`, whose merge deletes the class it beats rather than
        // trusting it to be printed later, so "max-h-none after max-h-[...]"
        // would in fact have worked -- but a reader would have to know that to
        // believe it, and the two boxes have almost nothing in common anyway.
        className={cn(
          // Resizes land in one paint. Before previews opted out of the
          // dialog's opening keyframes, `transition-property` was left at its
          // default of `all` -- so every property this popup changes after it
          // is on screen was being interpolated over 100ms, and half of them
          // cannot be. Going full-window snapped its height (`auto` to a
          // length interpolates to nothing) and its max-width, while the
          // width and the centering translate slid: the box jumped to the top
          // of the screen and then swung out from the left. A resize this
          // partial reads worse than no motion, and it was doing it to the
          // ordinary case too -- a preview grows when its picture finishes
          // decoding and the measured width replaces the floor.
          "isolate transition-none",
          fullscreen
            ? // Everything the centered box does, undone. The margin, the
              // rounding and the shadow are how a popup says it is sitting on
              // top of a page; full-window there is no page left to sit on,
              // so it stops saying it. The rows are named so that the body
              // can fill what the title bar leaves: `auto` would size the
              // body to the media and hand a portrait the height it asked
              // for, which is the scrolling this mode exists to end.
              "top-0 left-0 h-dvh max-w-none translate-x-0 translate-y-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-none shadow-none ring-0 sm:max-w-none"
            : cn(
                // Named here for the same reason the full-window box names
                // them, and against the same failure: `auto` sizes the second
                // row to what is in it, so a document taller than the screen
                // grows the popup rather than scrolling inside it -- and the
                // popup, being `overflow-auto` itself, becomes a second
                // scroller wrapped around the one the reader is using.
                // Reaching the end of a document then scrolls the dialog.
                "max-h-[calc(100dvh-2rem)] grid-rows-[auto_minmax(0,1fr)] overflow-auto",
                width === undefined ? "sm:max-w-4xl" : "sm:max-w-none",
                // A fixed-height reader already knows its top and height.
                // Centre it with auto margins instead of keeping the whole
                // document in a transformed raster layer.
                height !== undefined &&
                  "top-4 right-0 left-0 mx-auto translate-x-0 translate-y-0",
              ),
        )}
        // A size measured for a centered box is the wrong answer when the
        // answer is "the window".
        style={fullscreen ? undefined : { width, height }}
        {...{ [PREVIEW_FULLSCREEN_ATTR]: fullscreen ? "true" : undefined }}
      >
        <DialogHeader>
          {/* Quiet, the way a GUI label is quiet, and for the same reason: it
              names what is under it, and a name set as loudly as a heading
              competes with the one thing the popup was opened to show. A
              modal's title is a heading because a modal is a page of its own;
              a preview's is a caption. */}
          <DialogTitle className={cn(guiLabelClassName, "text-sm")}>
            {title}
          </DialogTitle>
        </DialogHeader>
        <FullscreenCorner
          fullscreen={fullscreen}
          onToggle={() => setFullscreen(!fullscreen)}
        />
        {/* The body is a box of its own only so that it has a height to give
            away: full-window the media and the document frame inside it both
            ask for all of it, and `h-full` needs something to be full of.
            A plain block, deliberately -- as a grid it sized its one row to
            the media's intrinsic height, and a percentage height against an
            auto track resolves to nothing, so the media fell back to its own
            size and ran off the bottom.
            Windowed it carries nothing at all, so that it stays what it looks
            like: a wrapper. Given `min-h-0` it let the popup's row shrink
            under the document frame inside it, and the popup grew a scrollbar
            of its own beside the frame's -- two nested scrollers, and a link
            that focused anything scrolled whichever the browser picked. */}
        <div className={cn(fullscreen && "h-full")}>{children}</div>
      </DialogContent>
    </Dialog>
  );
}
