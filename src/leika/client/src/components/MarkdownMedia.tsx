/**
 * The interactive half of images inside a Markdown document.
 *
 * The parsed document is cached by source, so it cannot capture a callback
 * from whichever surface happens to be showing it. A controller around that
 * immutable tree supplies the callback through context and owns the one media
 * preview the document can have open. Thirty figures still mean one dialog,
 * not thirty dormant dialog trees and fullscreen subscriptions.
 */

import * as React from "react";

import { InlineMediaSurface, MediaPreview } from "./MediaPreview";
import { mediaPreviewWidth, type MediaSize } from "./mediaPreviewSize";
import { inspectMarkdownImageSource } from "./markdownMediaSafety";
import {
  previewMediaClassName,
  usePreviewFullscreen,
} from "./previewFullscreen";
import {
  IMAGE_DECODE_FAILURE_MESSAGE,
  useImageDecodeError,
} from "../imageDecodeError";
import {
  RASTER_PIXEL_BUDGET_MESSAGE,
  useRasterPixelLease,
} from "../useRasterPixelLease";

interface MarkdownImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  /** Supplied only by MarkdownLink, so its button can be a sibling of the
   * anchor rather than invalid interactive content inside it. */
  linkedBy?: React.AnchorHTMLAttributes<HTMLAnchorElement>;
  src?: string;
}

type AdmittedMarkdownImageProps = MarkdownImageProps & {
  measured: MediaSize;
  sourceKind: "asset" | "data";
};

interface SelectedImage {
  alt: string;
  key: string;
  size: MediaSize | null;
  src: string;
  title: string;
  titleAttribute?: string;
}

interface MarkdownMediaContextValue {
  openImage: (image: SelectedImage) => void;
}

const MarkdownMediaContext =
  React.createContext<MarkdownMediaContextValue | null>(null);
const InsidePictureContext = React.createContext(false);
const InsideUnliftedLinkContext = React.createContext(false);

function SelectedImagePreview({
  image,
  open,
  onOpenChange,
}: {
  image: SelectedImage;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [fullscreen] = usePreviewFullscreen(image.key);
  const decodeError = useImageDecodeError(image.src);
  const pixels = useRasterPixelLease(image.src, image.size, open);
  return (
    <MediaPreview
      open={open}
      onOpenChange={onOpenChange}
      title={image.title}
      rememberAs={image.key}
      width={mediaPreviewWidth(image.size)}
    >
      {!pixels.pending && !pixels.admitted ? (
        <span role="status" className="text-muted-foreground text-sm">
          {RASTER_PIXEL_BUDGET_MESSAGE}{" "}
          <a href={image.src} rel="noreferrer noopener">
            Open image: {image.title}
          </a>
        </span>
      ) : decodeError.failed ? (
        <span role="status" className="text-muted-foreground text-sm">
          {IMAGE_DECODE_FAILURE_MESSAGE}{" "}
          <a href={image.src} rel="noreferrer noopener">
            Open image: {image.title}
          </a>
        </span>
      ) : pixels.admitted ? (
        <img
          src={image.src}
          alt={image.alt}
          title={image.titleAttribute}
          width={image.size?.width}
          height={image.size?.height}
          className={previewMediaClassName(fullscreen)}
          onError={decodeError.onError}
        />
      ) : null}
    </MediaPreview>
  );
}

/** Give one rendered document one shared image viewer. */
export function MarkdownMediaController({
  children,
}: {
  children: React.ReactNode;
}) {
  // Keep the selected image after closing until Dialog finishes its controlled
  // teardown, so its title and media cannot disappear independently.
  const [selected, setSelected] = React.useState<SelectedImage | null>(null);
  const [open, setOpen] = React.useState(false);
  const openImage = React.useCallback((image: SelectedImage) => {
    setSelected(image);
    setOpen(true);
  }, []);
  const context = React.useMemo(() => ({ openImage }), [openImage]);

  return (
    <MarkdownMediaContext value={context}>
      {children}
      {selected === null ? null : (
        <SelectedImagePreview
          image={selected}
          open={open}
          onOpenChange={setOpen}
        />
      )}
    </MarkdownMediaContext>
  );
}

/** The size the server measured for a picture it is serving, from its URL.
 *
 * It travels as a query rather than an HTML tag because a tag on a line of its
 * own opens an HTML block in Markdown. The query is invisible to the parser
 * and ignored by the asset server, while giving the browser a stable box
 * before the pixels arrive.
 */
function positiveDimension(value: number | string | undefined): number | null {
  if (value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function imageSize(
  element: HTMLImageElement | null,
  props: React.ImgHTMLAttributes<HTMLImageElement>,
): MediaSize | null {
  const width =
    positiveDimension(element?.naturalWidth) ?? positiveDimension(props.width);
  const height =
    positiveDimension(element?.naturalHeight) ??
    positiveDimension(props.height);
  return width === null || height === null ? null : { width, height };
}

/** A compact identity that survives closing and reopening the document.
 *
 * Asset URLs already carry a content digest, but a document may also use an
 * external URL or a multi-megabyte data URL. Keeping the source itself in the
 * global fullscreen flag would retain all of those bytes after the document
 * closes, so two independent 32-bit accumulators keep the identity without
 * keeping the payload. Length makes the already-remote collision still less
 * plausible.
 */
function imageMemoryKey(src: string): string {
  let first = 0x811c9dc5;
  let second = 0x9e3779b9;
  for (let index = 0; index < src.length; index += 1) {
    const code = src.charCodeAt(index);
    first = Math.imul(first ^ code, 0x01000193);
    second = Math.imul(second ^ code, 0x85ebca6b);
  }
  return `markdown-image:${src.length.toString(36)}:${(first >>> 0).toString(36)}:${(second >>> 0).toString(36)}`;
}

function anchorAround(
  image: React.ReactElement,
  linkedBy: React.AnchorHTMLAttributes<HTMLAnchorElement> | undefined,
): React.ReactElement {
  if (linkedBy === undefined) return image;
  return (
    <a {...linkedBy} rel="noreferrer noopener">
      {image}
    </a>
  );
}

/** An image made by Markdown, optionally interactive when a controller owns it. */
export function MarkdownImage({
  linkedBy,
  ...sourceProps
}: MarkdownImageProps) {
  const inspected = inspectMarkdownImageSource(sourceProps.src);
  const measured = inspected.admission.ok ? inspected.admission.size : null;
  const pixels = useRasterPixelLease(sourceProps.src ?? null, measured);
  if (sourceProps.src === undefined) {
    return (
      <span role="status" className="text-muted-foreground text-sm">
        Image preview is unavailable because its source is missing.
      </span>
    );
  }
  if (!inspected.admission.ok) {
    const title = sourceProps.alt?.trim() || "Image";
    return (
      <span role="status" className="text-muted-foreground text-sm">
        {inspected.admission.reason}{" "}
        <a
          href={sourceProps.src}
          download={inspected.sourceKind === "data" ? title : undefined}
          rel="noreferrer noopener"
        >
          Open image: {title}
        </a>
      </span>
    );
  }
  // From here admission succeeded, so the size passed to the hook is exact.
  if (measured === null) return null;
  if (!pixels.pending && !pixels.admitted) {
    const title = sourceProps.alt?.trim() || "Image";
    return (
      <span role="status" className="text-muted-foreground text-sm">
        {RASTER_PIXEL_BUDGET_MESSAGE}{" "}
        <a
          href={sourceProps.src}
          download={inspected.sourceKind === "data" ? title : undefined}
          rel="noreferrer noopener"
        >
          Open image: {title}
        </a>
      </span>
    );
  }
  if (!pixels.admitted) return null;
  return (
    <AdmittedMarkdownImage
      {...sourceProps}
      linkedBy={linkedBy}
      measured={measured}
      sourceKind={inspected.sourceKind === "asset" ? "asset" : "data"}
    />
  );
}

/** Draw an already-admitted image. Split from the lease gate so its markup
 * and link/button semantics remain testable without pretending SSR effects
 * can reserve a browser-only pixel owner. */
export function AdmittedMarkdownImage({
  linkedBy,
  measured,
  sourceKind,
  ...sourceProps
}: AdmittedMarkdownImageProps) {
  const controller = React.useContext(MarkdownMediaContext);
  const insidePicture = React.useContext(InsidePictureContext);
  const insideUnliftedLink = React.useContext(InsideUnliftedLinkContext);
  const imageRef = React.useRef<HTMLImageElement | null>(null);
  const decodeError = useImageDecodeError(sourceProps.src ?? null);
  if (sourceProps.src === undefined) return null;
  if (decodeError.failed) {
    const title = sourceProps.alt?.trim() || "Image";
    return (
      <span role="status" className="text-muted-foreground text-sm">
        {IMAGE_DECODE_FAILURE_MESSAGE}{" "}
        <a
          href={sourceProps.src}
          download={sourceKind === "data" ? title : undefined}
          rel="noreferrer noopener"
        >
          Open image: {title}
        </a>
      </span>
    );
  }

  const props = { ...sourceProps, ...measured };
  const canDefer = sourceKind === "asset";
  const image = (
    <img
      ref={imageRef}
      {...props}
      loading={canDefer ? "lazy" : props.loading}
      decoding={canDefer ? "async" : props.decoding}
      onError={decodeError.onError}
    />
  );

  // A picture's fallback image must remain its direct child. Likewise, a raw
  // link with mixed/whitespace children cannot safely lift one child out; it
  // keeps ordinary link behavior and no nested interactive control.
  if (
    controller === null ||
    insidePicture ||
    insideUnliftedLink ||
    props.src === undefined
  ) {
    return anchorAround(image, linkedBy);
  }

  const fallbackSrc = props.src;
  const title = props.alt?.trim() || "Image";
  const expand = () => {
    const element = imageRef.current;
    const src = element?.currentSrc || fallbackSrc;
    controller.openImage({
      alt: props.alt ?? "",
      key: imageMemoryKey(fallbackSrc),
      size: imageSize(element, props),
      src,
      title,
      titleAttribute: props.title,
    });
  };

  return (
    <InlineMediaSurface
      subject="image"
      accessibleLabel={`Expand image: ${title}`}
      onExpand={expand}
    >
      {anchorAround(image, linkedBy)}
    </InlineMediaSurface>
  );
}

/** A link that hoists a sole image's expand button beside the anchor. */
export function MarkdownLink({
  children,
  ...props
}: React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  const child = React.Children.toArray(children)[0];
  if (
    React.Children.count(children) === 1 &&
    React.isValidElement<MarkdownImageProps>(child) &&
    child.type === MarkdownImage
  ) {
    return React.cloneElement(child, {
      linkedBy: { ...props, children },
    });
  }
  return (
    <InsideUnliftedLinkContext value={true}>
      <a {...props} rel="noreferrer noopener">
        {children}
      </a>
    </InsideUnliftedLinkContext>
  );
}

/** Keep responsive-image selection valid; its fallback stays unwrapped. */
export function MarkdownPicture(
  props: React.HTMLAttributes<HTMLPictureElement>,
) {
  // `source[srcset]` starts fetching before a fallback component can inspect
  // the bytes. Render only the fallback image through MarkdownImage's safe
  // admission; responsive author sources remain inert rather than causing an
  // involuntary remote request.
  const fallbackImages = React.Children.toArray(props.children).filter(
    (child) =>
      React.isValidElement(child) &&
      (child.type === MarkdownImage || child.type === AdmittedMarkdownImage),
  );
  return (
    <InsidePictureContext value={false}>{fallbackImages}</InsidePictureContext>
  );
}
