import { PauseIcon, PlayIcon } from "lucide-react";
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
  label,
  disabled,
}: {
  videoRef: RefObject<HTMLVideoElement | null>;
  label: string;
  disabled: boolean;
}) {
  const [paused, setPaused] = useState(true);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(NaN);
  const [rate, setRate] = useState(1);
  const [speedOpen, setSpeedOpen] = useState(false);

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
      data-open={speedOpen}
      className="pointer-events-none absolute inset-x-1 bottom-1 flex h-8 items-center gap-2 rounded-md border bg-card px-1 text-card-foreground opacity-0 shadow-sm transition-opacity group-hover/video:pointer-events-auto group-hover/video:opacity-100 group-focus-within/video:pointer-events-auto group-focus-within/video:opacity-100 data-[open=true]:pointer-events-auto data-[open=true]:opacity-100 [@media(hover:none)]:pointer-events-auto [@media(hover:none)]:opacity-100"
    >
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
        {paused ? <PlayIcon /> : <PauseIcon />}
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
        onOpenChange={setSpeedOpen}
        onValueChange={(value) => {
          if (value !== null) videoRef.current!.playbackRate = value;
        }}
      >
        <SelectTrigger
          size="sm"
          className="shrink-0 gap-0.5 border-0 px-1 text-[11px] dark:bg-transparent"
          aria-label={`${label} playback speed`}
          title="Playback speed"
          disabled={disabled}
        >
          <SelectValue>{rate}×</SelectValue>
        </SelectTrigger>
        <SelectContent
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
    </div>
  );
}
