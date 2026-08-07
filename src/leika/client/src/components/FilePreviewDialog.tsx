import { DownloadIcon, FileIcon, RefreshCwIcon } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import {
  GUI_MESSAGE_THROTTLE_MS,
  useThrottledMessageSender,
} from "../WebsocketUtils";
import {
  closeFilePreview,
  filePreviewStore,
  formatBytes,
  isMediaKind,
  isReadingKind,
  previewKindFor,
  reloadIsOnItsWay,
  type FileContents,
  type FilePreview,
  type PreviewKind,
} from "../filePreview";
import { HintTooltip } from "./common";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { MediaPreview } from "./MediaPreview";
import { mediaPreviewWidth, useMediaSize } from "./mediaPreviewSize";
import {
  previewMediaClassName,
  usePreviewFullscreen,
} from "./previewFullscreen";

/** Read a textual blob without briefly rendering an empty document.
 *
 * The text lands as a transition: showing a document means parsing it, which
 * for a long file is real work, and work a transition lets React do after the
 * frame around the document has painted rather than before. The dialog is on
 * screen at the click, and the document arrives in it.
 */
function useBlobText(blob: Blob, enabled: boolean): string | null {
  const [text, setText] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!enabled) return;
    let current = true;
    blob.text().then(
      (value) => {
        if (current) React.startTransition(() => setText(value));
      },
      () => {
        if (current) setText("");
      },
    );
    return () => {
      current = false;
    };
  }, [blob, enabled]);
  return text;
}

/** Fallback for file types without an in-browser viewer. */
function UnsupportedPreview({
  filename,
  mimeType,
  sizeBytes,
}: {
  filename: string;
  mimeType: string;
  sizeBytes: number;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <FileIcon className="text-muted-foreground size-10" />
      <div>
        <p className="text-sm font-medium break-all">{filename}</p>
        <p className="text-muted-foreground text-xs">
          {mimeType} &middot; {formatBytes(sizeBytes)}
        </p>
      </div>
      <p className="text-muted-foreground max-w-sm text-xs">
        There is no viewer for this kind of file. Download it, with the button
        above, to open it in something that knows how.
      </p>
    </div>
  );
}

/** Download action, in the row of corner chrome.
 *
 * The corner reads outward from the close: the two nearest it -- close, and
 * the full-window toggle -- are about the POPUP, and the two beyond them are
 * about the file. Each is one 2rem step further in than the last, so the
 * close stays exactly where it is in every popup this app has.
 */
function DownloadCorner({ filename, url }: { filename: string; url: string }) {
  return (
    <HintTooltip hint="Download">
      <Button
        variant="ghost"
        size="icon-sm"
        className="absolute top-2 right-18"
        render={<a href={url} download={filename} />}
      >
        <DownloadIcon />
        <span className="sr-only">Download {filename}</span>
      </Button>
    </HintTooltip>
  );
}

/** Ask the button that sent this file for it again.
 *
 * Outermost of the four. A preview follows its file on its own -- see
 * {@link WATCH_INTERVAL_MS} -- so what this is for is the times watching
 * cannot answer: contents that are computed rather than read off disk, where
 * only running the caller's function again says what they are now, and which
 * nothing but a press is allowed to do.
 *
 * It spins while the answer is on its way, because the usual answer looks
 * like nothing happening: reload a file nobody has touched and the same
 * bytes come back into the same document. Without the spin the button would
 * read as broken exactly when it is working.
 */
function ReloadCorner({
  reloading,
  onReload,
}: {
  reloading: boolean;
  onReload: () => void;
}) {
  return (
    <HintTooltip hint="Reload">
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="absolute top-2 right-26"
        onClick={onReload}
        aria-label="Reload"
        data-leika-preview-reload
      >
        <RefreshCwIcon className={cn(reloading && "animate-spin")} />
      </Button>
    </HintTooltip>
  );
}

/** How long a pressed reload spins before admitting nothing is coming.
 *
 * Long enough that a slow file still stops it by arriving, short enough that
 * nobody is left watching it turn. */
const RELOAD_GIVE_UP_MS = 10_000;

/** The measure writing is read at here: short enough that the eye finds the
 * start of the next line, and the width `max-w-prose` is named for. */
const MEASURE = "65ch";

/** The surface a document is read on.
 *
 * Two things make writing readable, and neither is about the file: a measure
 * short enough that the eye finds the start of the next line, and type set for
 * reading rather than for fitting.
 *
 * The measure is named rather than imposed. This is the full width of the
 * popup, and the document lays its own blocks out inside it: prose keeps to a
 * reading column in the middle, and a table, which is not read a line at a
 * time, takes the whole of what the window has. A column clamped here would
 * have taken that choice away from every block at once.
 *
 * The size is the one thing this adds that the panel does not. Body copy in a
 * GUI row is 13px so that it lines up with the inputs around it, which is a
 * size for labels rather than for paragraphs. A preview has no inputs to line
 * up with, so it takes GitHub's 16px less the pixel this UI runs below stock
 * everywhere else. Everything the markdown renderer draws is sized in `em`,
 * so headings, code and tables all follow from this one number.
 */
function ReadingColumn({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="w-full px-2 text-[0.9375rem]"
      style={{ "--measure": MEASURE } as React.CSSProperties}
    >
      {children}
    </div>
  );
}

/** What the popup holds while there is nothing to hold yet: the file still
 * arriving, or a document still being read out of it. One mark for both, so
 * the wait reads as one wait however it is being spent.
 *
 * Fills a document's frame, and carries its own height where there is no
 * frame -- media has none, and a spinner in a box of no height is nothing. */
function PendingBody() {
  return (
    <div className="flex h-full min-h-40 items-center justify-center">
      <Spinner className="text-muted-foreground size-6" />
    </div>
  );
}

/** Render the file, in the frame a document gets and media does not. */
function PreviewBody({
  kind,
  preview,
  contents,
}: {
  kind: PreviewKind;
  preview: FilePreview;
  contents: FileContents;
}) {
  const { filename, mimeType, sizeBytes } = preview;
  const { url, blob } = contents;
  const isTextual = kind === "text" || kind === "prose" || kind === "markdown";
  const text = useBlobText(blob, isTextual);
  const [fullscreen] = usePreviewFullscreen(filename);

  switch (kind) {
    // The three that are shown at their own size. The popup has already been
    // opened at the media's width -- see `mediaPreviewWidth` at the bottom of
    // this file -- so each of these fills it, rather than being centered in
    // something wider with a column of empty dialog down either side.
    case "image":
      return (
        <img
          src={url}
          alt={filename}
          className={previewMediaClassName(fullscreen)}
        />
      );
    case "video":
      return (
        <video
          src={url}
          controls
          className={previewMediaClassName(fullscreen)}
        />
      );
    case "audio":
      // Not sized like the other two: a player is a bar, and stretching it
      // down a full-window popup would only make a taller bar. It keeps the
      // width and stays where a caption would be.
      return <audio src={url} controls className="block w-full" />;
    case "pdf":
      // Let browsers without a PDF viewer render the fallback children.
      return (
        <object
          data={url}
          type="application/pdf"
          className="h-full w-full rounded-lg"
        >
          <UnsupportedPreview
            filename={filename}
            mimeType={mimeType}
            sizeBytes={sizeBytes}
          />
        </object>
      );
    case "markdown":
      // The spinner from the transfer holds until the document is ready to
      // land whole, in one paint.
      if (text === null) return <PendingBody />;
      return (
        <ReadingColumn>
          {/* The one surface with margins to put a contents list in: the
              writing keeps to its measure, and what is left over on either
              side is room a preview has and a panel row does not. */}
          <MarkdownRenderer contents>{text}</MarkdownRenderer>
        </ReadingColumn>
      );
    case "prose":
      return (
        <ReadingColumn>
          {/* Unrendered writing, so the lines are the author's: monospace,
              a touch smaller than prose that has been typeset, and wrapped
              rather than scrolled because a paragraph is not a record. It is
              the whole document, so it holds the measure itself rather than
              leaving blocks to. */}
          <pre className="mx-auto max-w-[var(--measure)] font-mono text-[0.85em] leading-[1.5] whitespace-pre-wrap">
            {text ?? ""}
          </pre>
        </ReadingColumn>
      );
    case "text":
      return (
        // Preserve data and source lines, scrolling horizontally when needed.
        <pre className="bg-muted/40 min-h-full w-full overflow-x-auto rounded-lg p-4 font-mono text-xs whitespace-pre">
          {text ?? ""}
        </pre>
      );
    case "unsupported":
      return (
        <UnsupportedPreview
          filename={filename}
          mimeType={mimeType}
          sizeBytes={sizeBytes}
        />
      );
  }
}

/** How often an open preview asks whether its file has moved on.
 *
 * A second is about as long as it is worth staring at a document that has
 * been rewritten -- save in the editor, glance at the browser, and it is
 * already the new one -- and it costs a `stat` and a message that carries a
 * name and a timestamp. Only ever one preview is open, so this is the whole
 * of the traffic, and none of it is bytes unless the file really changed.
 *
 * Asking is the browser's job rather than the server's on purpose: a tab that
 * is closed, refreshed or crashed simply stops asking, where a watcher on the
 * server would have to be told, and would keep a thread on a file nobody is
 * looking at until it was.
 */
const WATCH_INTERVAL_MS = 1000;

/** Mount point for previews, one per app.
 *
 * The half of a preview that talks to the server: the dialog below draws a
 * file and says when the reader wants another look at it, and this is what
 * turns that into messages. The playground renders the dialog with neither,
 * and gets a preview that simply sits there, which is what a gallery wants.
 */
export function FilePreviewHost() {
  const preview = React.useSyncExternalStore(
    filePreviewStore.subscribe,
    filePreviewStore.snapshot,
    filePreviewStore.snapshot,
  );
  const { send } = useThrottledMessageSender(GUI_MESSAGE_THROTTLE_MS);
  const sourceUuid = preview?.sourceUuid ?? null;
  const version = preview?.sourceVersion ?? null;

  React.useEffect(() => {
    // A source with no version is one that cannot be watched -- bytes, or a
    // function whose answer only a press may ask for -- so there is nothing
    // to ask about and the timer never starts.
    if (sourceUuid === null || version === null) return;
    const timer = window.setInterval(() => {
      // A background tab is not being read. Its timers are throttled to
      // roughly this interval anyway, and the file it wants is the one it
      // has when the reader comes back, which the next tick will fetch.
      if (document.hidden) return;
      // The last answer is still arriving. Asking again would fetch the same
      // file a second time, since the version it would be compared against is
      // still the one this dialog is showing.
      if (reloadIsOnItsWay(sourceUuid)) return;
      send({ type: "GuiPreviewWatchMessage", uuid: sourceUuid, version });
    }, WATCH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [sourceUuid, version, send]);

  const reload = React.useCallback(() => {
    if (sourceUuid === null) return;
    // An event, not a state: two presses are two asks, and the second must
    // not replace the first inside a throttle window and go unsent.
    send(
      { type: "GuiPreviewReloadMessage", uuid: sourceUuid },
      { coalesce: false },
    );
  }, [sourceUuid, send]);

  if (preview === null) return null;
  return (
    <FilePreviewDialog
      // Remount stateful media viewers for each transfer.
      key={preview.id}
      preview={preview}
      onClose={() => closeFilePreview(preview.id)}
      onReload={sourceUuid === null ? undefined : reload}
    />
  );
}

/** How tall a DOCUMENT opens.
 *
 * Fixed, so a preview opens the same size whatever the file turns out to hold
 * -- a one-line log and a thousand-line one are the same window, and nothing
 * jumps as the contents arrive, which matters because the popup is on screen
 * before them. Media has no frame at all; see {@link isMediaKind}.
 *
 * Writing gets everything the window has: the height is the POPUP's, and the
 * frame inside it takes whatever the title bar and the padding leave, because
 * the popup's grid hands its second row the remainder. It used to be the
 * frame that carried a height -- the window less a hand-counted 6rem of
 * chrome -- and the count was 3px short of what the chrome actually measured,
 * which is enough to make the popup a scroller in its own right: scrolling to
 * the end of a document then scrolled the dialog underneath it. A frame sized
 * by layout cannot disagree with the box around it.
 *
 * Which is what full-window has always done, there being no guess available
 * to make: the frame takes the body it is given. The two are one case now.
 *
 * A PDF or a card keeps a frame of its own, and a shorter one, because it is
 * looked at rather than read down and the extra height would only be empty
 * space around it.
 */
const READING_HEIGHT = "calc(100dvh - 2rem)";
const FITTED_FRAME_HEIGHT = "h-[70dvh]";

/** How wide a document opens: as much of the window as it can have, short of
 * the edges. A document has no width of its own to ask for. */
const DOCUMENT_WIDTH = "min(72rem, calc(100vw - 2rem))";

/** A file, in the popup its kind calls for.
 *
 * Media opens at its own size, in the same popup a pane's expand button
 * opens; a document opens in a fixed frame. Which of the two is settled by
 * the name and the MIME type, both of which arrive with the transfer's first
 * message -- so the popup is the right shape from the click, and only the
 * contents wait.
 */
export function FilePreviewDialog({
  preview,
  onClose,
  onReload,
}: {
  preview: FilePreview;
  onClose: () => void;
  /** Ask for the file again. Absent when there is nothing to ask -- a file a
   * script sent names no component the browser could go back to. */
  onReload?: () => void;
}) {
  const kind = previewKindFor(preview.mimeType, preview.filename);
  const media = isMediaKind(kind);
  // Only a picture says how big it is. Audio has no size at all, and a
  // video's is not worth a second decode to learn, so both open at the floor.
  const imageSize = useMediaSize(
    kind === "image" ? (preview.contents?.url ?? null) : null,
  );
  // Read rather than passed down: the popup owns the toggle, and the document
  // frame is the one thing inside it that has to know.
  const [fullscreen] = usePreviewFullscreen(preview.filename);

  // Which contents the reader asked to be rid of. The spin lasts until they
  // are not what is on screen any more, so the answer itself stops it --
  // whatever the answer took, and whether or not it differs.
  const [asked, setAsked] = React.useState<FileContents | null>(null);
  const reloading = asked !== null && asked === preview.contents;
  React.useEffect(() => {
    if (!reloading) return;
    // Nothing came. A button removed from the panel while its preview was
    // open answers nothing at all, and a spinner that never stops says the
    // app is stuck when only this one ask is.
    const timer = window.setTimeout(() => setAsked(null), RELOAD_GIVE_UP_MS);
    return () => window.clearTimeout(timer);
  }, [reloading]);

  const body =
    preview.contents === null ? (
      <PendingBody />
    ) : (
      <PreviewBody kind={kind} preview={preview} contents={preview.contents} />
    );

  const reading = isReadingKind(kind);

  return (
    <MediaPreview
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={preview.filename}
      // The file's name. A transfer's uuid is new on every press, and the
      // button that sent it is not named on the wire -- but the name is what
      // the transfer announces first, and it is already what a warmed
      // preview is filed under.
      rememberAs={preview.filename}
      width={media ? mediaPreviewWidth(imageSize) : DOCUMENT_WIDTH}
      height={reading ? READING_HEIGHT : undefined}
    >
      {/* Both wait for the file. There is nothing to save before it lands,
          and nothing to ask for again either -- the first copy is still on
          its way. */}
      {preview.contents !== null && onReload !== undefined && (
        <ReloadCorner
          reloading={reloading}
          onReload={() => {
            setAsked(preview.contents);
            onReload();
          }}
        />
      )}
      {preview.contents !== null && (
        <DownloadCorner
          filename={preview.filename}
          url={preview.contents.url}
        />
      )}
      {media ? (
        body
      ) : (
        <div
          className={cn(
            // `min-h-0` is what lets the frame be shorter than the document
            // in it, so the scroll happens here. `overscroll-contain` keeps
            // that scroll here as well: reaching the end of a document is the
            // end of it, not a nudge passed outwards to whatever box the
            // popup happens to sit in.
            "min-h-0 overflow-auto overscroll-contain",
            // Both the full-window popup and the reading one are a definite
            // height with a title bar above the frame, so the frame fills
            // what is left of the row either way.
            fullscreen || reading ? "h-full" : FITTED_FRAME_HEIGHT,
          )}
        >
          {body}
        </div>
      )}
    </MediaPreview>
  );
}
