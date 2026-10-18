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
import {
  PreviewImageSourcesContext,
  previewImageSourceKey,
} from "../previewImageSources";

import { cn } from "@/lib/utils";

import { MediaImage } from "./MediaImage";
import { InlineMediaSurface, MediaPreview } from "./MediaPreview";
import { mediaPreviewWidth, type MediaSize } from "./mediaPreviewSize";
import { markdownImageSource } from "./markdownMediaSafety";
import {
  previewMediaClassName,
  usePreviewFullscreen,
} from "./previewFullscreen";

interface MarkdownImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  /** Supplied only by MarkdownLink, so its button can be a sibling of the
   * anchor rather than invalid interactive content inside it. */
  linkedBy?: React.AnchorHTMLAttributes<HTMLAnchorElement>;
  src?: string;
}

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
  return (
    <MediaPreview
      open={open}
      onOpenChange={onOpenChange}
      title={image.title}
      rememberAs={image.key}
      width={mediaPreviewWidth(image.size)}
    >
      <MediaImage
        src={image.src}
        alt={image.alt}
        title={image.titleAttribute}
        width={image.size?.width}
        height={image.size?.height}
        className={previewMediaClassName(fullscreen)}
      />
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

/** A compact identity that survives closing and reopening the document.
 *
 * Asset URLs already carry a content digest, but a document may also use a
 * multi-megabyte data URL. Keeping the source itself in the global fullscreen
 * flag would retain all of those bytes after the document closes, so two
 * independent 32-bit accumulators keep the identity without keeping the
 * payload. Length makes the already-remote collision still less plausible.
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
  const controller = React.useContext(MarkdownMediaContext);
  const insideUnliftedLink = React.useContext(InsideUnliftedLinkContext);
  const preview = React.useContext(PreviewImageSourcesContext);
  const imageRef = React.useRef<HTMLImageElement | null>(null);

  // A streamed preview names its figures relative to the document until the
  // server has registered each one.
  let resolved: string | undefined;
  try {
    resolved = preview?.sources?.get(
      previewImageSourceKey(sourceProps.src ?? ""),
    );
  } catch {
    // An unparseable reference resolves to nothing, like an unknown one.
  }
  if (preview?.pending && resolved === undefined) {
    return sourceProps.alt
      ? anchorAround(
          <span className="block text-center text-sm text-muted-foreground">
            {sourceProps.alt}
          </span>,
          linkedBy,
        )
      : null;
  }
  const src = resolved ?? sourceProps.src;
  const source = markdownImageSource(src);
  if (src === undefined || source.kind === "blocked") {
    // Never fetched: the image is a link the reader can choose to follow.
    const text = sourceProps.alt?.trim() || src;
    const link =
      linkedBy ??
      (src === undefined || insideUnliftedLink ? undefined : { href: src });
    return anchorAround(<>{text}</>, link);
  }

  // A measured asset's box is already reserved, so its fetch can wait until
  // the reader nears it without moving the document when it lands.
  const deferred = source.size !== null;
  const image = (
    <MediaImage
      ref={imageRef}
      {...sourceProps}
      src={src}
      width={source.size?.width ?? sourceProps.width}
      height={source.size?.height ?? sourceProps.height}
      className={cn(
        "text-center text-sm text-muted-foreground",
        sourceProps.className,
      )}
      loading={deferred ? "lazy" : sourceProps.loading}
      decoding={deferred ? "async" : sourceProps.decoding}
    />
  );

  // A raw link with mixed/whitespace children cannot safely lift one child
  // out; it keeps ordinary link behavior and no nested interactive control.
  if (controller === null || insideUnliftedLink) {
    return anchorAround(image, linkedBy);
  }

  const title = sourceProps.alt?.trim() || "Image";
  const expand = () => {
    const element = imageRef.current;
    controller.openImage({
      alt: sourceProps.alt ?? "",
      key: imageMemoryKey(src),
      size:
        element !== null && element.naturalWidth > 0
          ? { width: element.naturalWidth, height: element.naturalHeight }
          : source.size,
      src,
      title,
      titleAttribute: sourceProps.title,
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

/** Draw only a picture's fallback image.
 *
 * `source[srcset]` starts fetching before anything can decide whether its
 * address is one a document may load, so author sources are dropped and the
 * fallback goes through MarkdownImage like any other image.
 */
export function MarkdownPicture(
  props: React.HTMLAttributes<HTMLPictureElement>,
) {
  return (
    <>
      {React.Children.toArray(props.children).filter(
        (child) => React.isValidElement(child) && child.type === MarkdownImage,
      )}
    </>
  );
}
