import { IMAGE_FIT_OBJECT_FIT } from "../ClientSettings";
import { MediaImage } from "../components/MediaImage";
import { useObjectUrl } from "../components/useObjectUrl";
import { useViewer } from "../ViewerContext";
import type { ViewportImagePane } from "./ViewportState";

export function ViewportImageRenderer({ pane }: { pane: ViewportImagePane }) {
  const viewer = useViewer();
  // An app that named a fit meant it; one that did not leaves the choice to
  // whoever is looking at the image.
  const preferredFit = viewer.useSettings((state) => state.imageFit);
  const fit = IMAGE_FIT_OBJECT_FIT[pane.props.fit ?? preferredFit];
  // An update changes the source of one persistent image, which keeps showing
  // the previous frame until the next has loaded.
  const imageUrl = useObjectUrl(
    pane.props._data,
    `image/${pane.props._format}`,
  );

  if (imageUrl === null) {
    return (
      <span
        style={{
          display: "flex",
          width: "100%",
          height: "100%",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--leika-media-background)",
          color: "#888",
          fontSize: "var(--text-sm)",
        }}
      >
        No image
      </span>
    );
  }

  return (
    <MediaImage
      src={imageUrl}
      alt={pane.props.title}
      draggable={false}
      style={{
        display: "block",
        width: "100%",
        height: "100%",
        objectFit: fit,
        userSelect: "none",
        background: "var(--leika-media-background)",
      }}
    />
  );
}
