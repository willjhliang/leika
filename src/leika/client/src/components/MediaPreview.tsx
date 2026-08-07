import { Maximize2Icon } from "lucide-react";
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
  onExpand,
}: {
  /** What is being expanded, lowercase: completes "Expand ___". */
  subject: string;
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
        aria-label={label}
      >
        <Maximize2Icon />
      </Button>
    </HintTooltip>
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
  width,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** CSS width for the dialog. Defaults to the stock 4xl content width. */
  width?: string;
  children: React.ReactNode;
}) {
  const popupRef = React.useRef<HTMLDivElement | null>(null);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        ref={popupRef}
        initialFocus={popupRef}
        finalFocus={false}
        className={cn(
          "max-h-[calc(100dvh-2rem)] overflow-auto",
          width === undefined ? "sm:max-w-4xl" : "sm:max-w-none",
        )}
        style={width === undefined ? undefined : { width }}
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
        {children}
      </DialogContent>
    </Dialog>
  );
}
