import { MaximizeIcon, MinimizeIcon, PauseIcon, PlayIcon } from "lucide-react";
import { useEffect, useState, type RefObject } from "react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";

const PLAYBACK_RATES = [0.25, 0.5, 1, 1.5, 2];

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds)) return "–:––";
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const remainder = String(whole % 60).padStart(2, "0");
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${remainder}`
    : `${minutes}:${remainder}`;
}

/** Media events update only this bar; playback never travels through Python. */
export function VideoPlaybackControls({
  videoRef,
  playerRef,
  label,
  disabled,
}: {
  videoRef: RefObject<HTMLVideoElement | null>;
  playerRef: RefObject<HTMLDivElement | null>;
  label: string;
  disabled: boolean;
}) {
  const [paused, setPaused] = useState(true);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(NaN);
  const [rate, setRate] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    const sync = () => {
      setFullscreen(document.fullscreenElement === playerRef.current);
    };
    sync();
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, [playerRef]);

  useEffect(() => {
    const video = videoRef.current!;
    const sync = () => {
      setPaused(video.paused);
      setTime(video.currentTime);
      setDuration(video.duration);
      setRate(video.playbackRate);
    };
    const events = [
      "play",
      "pause",
      "ended",
      "timeupdate",
      "loadedmetadata",
      "durationchange",
      "ratechange",
      "emptied",
    ];
    sync();
    events.forEach((event) => video.addEventListener(event, sync));
    return () => {
      events.forEach((event) => video.removeEventListener(event, sync));
    };
  }, [videoRef]);

  const canSeek = Number.isFinite(duration) && duration > 0 && !disabled;
  return (
    <div
      role="group"
      aria-label={`${label} playback`}
      className="absolute inset-x-0 bottom-0 p-1 opacity-0 hover:opacity-100 [@media(hover:none)]:opacity-100"
    >
      <div className="flex h-8 items-center gap-2 rounded-md border bg-card px-1 text-card-foreground shadow-sm">
        <Button
          variant="ghost"
          size="icon-xs"
          className="shrink-0"
          aria-label={`${paused ? "Play" : "Pause"} ${label}`}
          title={paused ? "Play" : "Pause"}
          disabled={disabled}
          onClick={() => {
            const video = videoRef.current!;
            if (video.paused) void video.play().catch(() => {});
            else video.pause();
          }}
        >
          {paused ? (
            <PlayIcon fill="currentColor" strokeWidth={0} />
          ) : (
            <PauseIcon fill="currentColor" strokeWidth={0} />
          )}
        </Button>
        <div className="min-w-4 flex-1">
          <Slider
            value={[canSeek ? Math.min(time, duration) : 0]}
            min={0}
            max={canSeek ? duration : 1}
            step={0.1}
            largeStep={5}
            disabled={!canSeek}
            getThumbAriaLabel={() => `Seek ${label}`}
            format={{ style: "unit", unit: "second" }}
            onValueChange={(value) => {
              const next = Array.isArray(value) ? value[0] : value;
              videoRef.current!.currentTime = next;
              setTime(next);
            }}
          />
        </div>
        <span className="shrink-0 text-[11px] tabular-nums" aria-hidden="true">
          {formatTime(time)}
          <span className="@max-[260px]:hidden text-muted-foreground">
            {" / "}
            {formatTime(duration)}
          </span>
        </span>
        <Select
          value={rate}
          onValueChange={(value) => {
            if (value !== null) videoRef.current!.playbackRate = value;
          }}
        >
          <SelectTrigger
            size="sm"
            className="shrink-0 gap-0.5 border-0 px-1 py-0 text-[11px] hover:bg-muted data-[size=sm]:h-6 dark:bg-transparent dark:hover:bg-muted/50"
            aria-label={`${label} playback speed`}
            title="Playback speed"
            disabled={disabled}
          >
            <SelectValue>{rate}×</SelectValue>
          </SelectTrigger>
          <SelectContent
            container={fullscreen ? playerRef : undefined}
            side="top"
            align="end"
            alignItemWithTrigger={false}
            className="min-w-20"
          >
            {PLAYBACK_RATES.map((value) => (
              <SelectItem key={value} value={value}>
                {value}×
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant="ghost"
          size="icon-xs"
          className="shrink-0"
          aria-label={`${fullscreen ? "Exit fullscreen" : "Fullscreen"} ${label}`}
          title={fullscreen ? "Exit fullscreen" : "Fullscreen"}
          disabled={!document.fullscreenEnabled}
          onClick={() => {
            const player = playerRef.current!;
            const request =
              document.fullscreenElement === player
                ? document.exitFullscreen()
                : player.requestFullscreen();
            void request.catch(() => {});
          }}
        >
          {fullscreen ? <MinimizeIcon /> : <MaximizeIcon />}
        </Button>
      </div>
    </div>
  );
}
