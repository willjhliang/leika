import { memo, useEffect, useRef, useState } from "react";
import { useViewer } from "../ViewerContext";
import { VideoPlaybackControls } from "./VideoPlaybackControls";
import { videoPlaybackKey } from "./videoPlayback";
import type { ViewportVideoPane } from "./ViewportState";

const Video = memo(function Video({ pane }: { pane: ViewportVideoPane }) {
  const viewer = useViewer();
  const pageId = viewer.useViewport((s) => s.displayPageId) ?? "";
  const key = videoPlaybackKey(pane, pageId);
  const playback = viewer.videoPlayback.get(key);
  const ref = useRef<HTMLVideoElement>(null);
  const playerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState(false);
  const { paneId, props: options } = pane;
  const visible = useRef(options.visible);
  visible.current = options.visible;
  useEffect(() => viewer.videoPlayback.retain(key), [viewer, key]);
  useEffect(() => {
    const video = ref.current!;
    const binding = playback.attach(paneId, video);
    const observer = new IntersectionObserver(([entry]) => {
      binding.visible(entry.isIntersecting && visible.current);
    });
    observer.observe(video);
    return () => {
      observer.disconnect();
      binding.remove();
    };
  }, [playback, paneId]);
  return (
    <div
      ref={playerRef}
      className="group/video @container relative h-full w-full"
    >
      <video
        ref={ref}
        src={options._url}
        aria-label={options.title}
        muted={options.muted}
        playsInline
        preload="auto"
        onError={() => setError(true)}
        onLoadedData={() => setError(false)}
        style={{
          display: "block",
          width: "100%",
          height: "100%",
          background: "var(--leika-media-background)",
          objectFit: "contain",
        }}
      />
      {options.controls && (
        <VideoPlaybackControls
          playback={playback}
          playerRef={playerRef}
          label={options.title}
          grouped={options.sync_group !== null}
        />
      )}
      {error && (
        <p role="alert" style={{ position: "absolute", inset: 12 }}>
          Could not play this video. Check its URL and browser codec support.
        </p>
      )}
    </div>
  );
});

export function ViewportVideoRenderer({ pane }: { pane: ViewportVideoPane }) {
  // A new media source or clock gets its own element, so queued native events
  // from the previous owner cannot change the new controller's playback intent.
  return (
    <Video
      key={JSON.stringify([pane.props._url, pane.props.sync_group])}
      pane={pane}
    />
  );
}
