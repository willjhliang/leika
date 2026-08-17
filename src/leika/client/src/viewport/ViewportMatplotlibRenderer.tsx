import React from "react";

import { matplotlibSvgSourceError } from "../rendererSourceLimits";
import {
  matchingSourceObjectUrlOwner,
  MATPLOTLIB_DECODE_FAILURE_MESSAGE,
  releaseFailedObjectUrl,
  type SourceObjectUrlOwner,
  useImageDecodeError,
} from "../imageDecodeError";
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
  const svg: unknown = pane.props._svg;
  const sourceError = matplotlibSvgSourceError(svg);
  const [owner, setOwner] = React.useState<SourceObjectUrlOwner | null>(null);

  // Display ownership may lag the target while its replacement is prepared.
  // Exact matching attributes failures; it must not discard the last good SVG.
  const currentOwner = matchingSourceObjectUrlOwner(owner, svg);
  const ownedObjectUrl = owner?.objectUrl ?? null;
  const decodeError = useImageDecodeError(ownedObjectUrl);
  const targetDecodeFailed =
    currentOwner?.objectUrl != null && decodeError.failed;
  const displayObjectUrl = decodeError.failed ? null : ownedObjectUrl;

  React.useEffect(() => {
    if (sourceError !== null || typeof svg !== "string") {
      setOwner(null);
      return;
    }

    let url: string;
    try {
      url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
    } catch (error) {
      console.error("Matplotlib figure setup failed:", error);
      setOwner({
        source: svg,
        objectUrl: null,
        renderError: "Matplotlib figure failed to render.",
      });
      return;
    }
    setOwner({ source: svg, objectUrl: url, renderError: null });
    return () => URL.revokeObjectURL(url);
  }, [sourceError, svg]);

  React.useEffect(
    () => releaseFailedObjectUrl(ownedObjectUrl, decodeError.failed),
    [decodeError.failed, ownedObjectUrl],
  );
  const message =
    sourceError ??
    currentOwner?.renderError ??
    (targetDecodeFailed ? MATPLOTLIB_DECODE_FAILURE_MESSAGE : null);
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        background: "var(--background)",
      }}
    >
      {message === null ? null : (
        <div
          className="flex h-full items-center justify-center p-4 text-center text-sm text-muted-foreground"
          role="status"
        >
          {message}
        </div>
      )}
      {message !== null || displayObjectUrl === null ? null : (
        <img
          src={displayObjectUrl}
          alt={pane.props.title}
          draggable={false}
          onError={decodeError.onError}
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
