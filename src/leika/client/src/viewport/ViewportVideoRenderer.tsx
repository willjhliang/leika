import { memo, useEffect, useRef, useState } from "react";
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
    <figure style={{ margin: 0, minWidth: 0 }}>
      <video
        ref={ref}
        src={url}
        aria-label={label}
        loop={options.loop}
        muted={options.muted}
        controls={options.controls}
        playsInline
        preload="metadata"
        onError={() => setError(true)}
        onLoadedData={() => setError(false)}
        style={{
          display: "block",
          width: "100%",
          aspectRatio: "16 / 9",
          background: "#101318",
          objectFit: "contain",
        }}
      />
      <figcaption style={{ padding: "6px 2px", fontSize: 12 }}>
        {label}
      </figcaption>
      {error && (
        <p role="alert">
          Could not play this video. Check its URL and browser codec support.
        </p>
      )}
    </figure>
  );
});

export function ViewportVideoRenderer({ pane }: { pane: ViewportVideoPane }) {
  const occurrences = new Map<string, number>();
  return (
    <div
      data-video-gallery
      style={{ width: "100%", height: "100%", overflow: "auto", padding: 10 }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${pane.props.columns}, minmax(0, 1fr))`,
          gap: 10,
        }}
      >
        {pane.props._videos.map(([label, url]) => {
          const occurrence = occurrences.get(url) ?? 0;
          occurrences.set(url, occurrence + 1);
          return (
            <Video
              key={`${url}:${occurrence}`}
              url={url}
              label={label}
              options={pane.props}
            />
          );
        })}
      </div>
    </div>
  );
}
