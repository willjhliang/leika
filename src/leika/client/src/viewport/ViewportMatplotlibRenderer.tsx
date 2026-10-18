import { MediaImage } from "../components/MediaImage";
import { useObjectUrl } from "../components/useObjectUrl";
import type { ViewportMatplotlibPane } from "./ViewportState";

/** Static matplotlib figure, relayed as SVG.
 *
 * Render through an `img` rather than inlining into the document: SVG can
 * carry script, and an image context cannot run it. Vector scales for free,
 * so a pane resize needs no redraw in Python. */
export default function ViewportMatplotlibRenderer({
  pane,
}: {
  pane: ViewportMatplotlibPane;
}) {
  const figureUrl = useObjectUrl(pane.props._svg, "image/svg+xml");
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        background: "var(--background)",
      }}
    >
      {figureUrl === null ? null : (
        <MediaImage
          src={figureUrl}
          alt={pane.props.title}
          draggable={false}
          style={{
            display: "block",
            width: "100%",
            height: "100%",
            objectFit: "contain",
          }}
        />
      )}
    </div>
  );
}
