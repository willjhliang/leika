import { memo, useEffect, useRef, useState } from "react";
import { VideoPlaybackControls } from "./VideoPlaybackControls";
import type { ViewportVideoPane, ViewportVideoProps } from "./ViewportState";

const Video = memo(function Video({
  url,
  label,
  options,
}: {
  url: string;
  label: string;
  options: ViewportVideoProps;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const playerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState(false);
  const wantsPlayback = useRef(options.autoplay);
  const automaticPauses = useRef(0);
  useEffect(() => {
    wantsPlayback.current = options.autoplay;
  }, [url, options.autoplay]);
  useEffect(() => {
    const video = ref.current!;
    const onPlay = () => {
      wantsPlayback.current = true;
    };
    const onPause = () => {
      if (automaticPauses.current > 0) automaticPauses.current--;
      else wantsPlayback.current = false;
    };
    video.addEventListener("play", onPlay);
    video.addEventListener("pause", onPause);
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting || !options.visible) {
        if (!video.paused) {
          automaticPauses.current++;
          video.pause();
        }
      } else if (wantsPlayback.current) {
        void video.play().catch(() => {});
      }
    });
    observer.observe(video);
    return () => {
      observer.disconnect();
      video.removeEventListener("play", onPlay);
      video.removeEventListener("pause", onPause);
    };
  }, [url, options.autoplay, options.visible]);
  return (
    <div
      ref={playerRef}
      className="group/video @container relative h-full w-full"
    >
      <video
        ref={ref}
        src={url}
        aria-label={label}
        loop={options.loop}
        muted={options.muted}
        playsInline
        preload="metadata"
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
          videoRef={ref}
          playerRef={playerRef}
          label={label}
          disabled={error}
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
  return (
    <Video
      key={pane.props._url}
      url={pane.props._url}
      label={pane.props.title}
      options={pane.props}
    />
  );
}
