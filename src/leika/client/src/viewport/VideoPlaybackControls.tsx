import {
  MaximizeIcon,
  MinimizeIcon,
  PauseIcon,
  PlayIcon,
  RepeatIcon,
  StepBackIcon,
  StepForwardIcon,
} from "lucide-react";
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
import type { VideoPlayback } from "./videoPlayback";

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

/** The dock and every fullscreen overlay subscribe to the same controller. */
export function VideoPlaybackControls({
  playback,
  playerRef,
  label: controlLabel,
  grouped = false,
}: {
  playback: VideoPlayback;
  playerRef?: RefObject<HTMLDivElement | null>;
  label: string | null;
  grouped?: boolean;
}) {
  const { paused, time, duration, rate, fps, loop, buffering, error } =
    playback.state();
  const [fullscreen, setFullscreen] = useState(false);
  useEffect(() => {
    const sync = () =>
      setFullscreen(
        playerRef !== undefined &&
          document.fullscreenElement === playerRef.current,
      );
    sync();
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, [playerRef]);
  const dock = playerRef === undefined;
  const compact = dock && controlLabel !== null;
  const label = controlLabel ?? "Playback";
  const status = error
    ? "Could not load a video in this group."
    : buffering
      ? "Waiting for video…"
      : undefined;
  const fullControls = dock || !grouped || fullscreen;
  const canSeek = duration > 0 && !error;
  const timeline = (
    <Slider
      value={[canSeek ? Math.min(time, duration) : 0]}
      min={0}
      max={canSeek ? duration : 1}
      step={fps === null ? 0.1 : 1 / fps}
      largeStep={5}
      disabled={!canSeek}
      getThumbAriaLabel={() => `Seek ${label}`}
      format={{ style: "unit", unit: "second" }}
      onValueChange={(value) =>
        playback.seek(Array.isArray(value) ? value[0] : value)
      }
    />
  );
  return (
    <div
      role="group"
      aria-label={`${label} playback`}
      title={dock ? status : undefined}
      className={
        dock
          ? "min-w-0"
          : `absolute right-0 bottom-0 p-1 opacity-0 group-hover/video:opacity-100 [@media(hover:none)]:opacity-100 ${fullControls ? "left-0" : ""}`
      }
    >
      {/* Each item contributes a 6px content inset, giving a 12px visible gap.
          The 24px icon buttons already inset their 12px icons by 6px; the
          speed trigger uses 5px padding plus its 1px transparent border. */}
      <div
        className={`flex min-w-0 items-center rounded-md ${compact ? "h-6" : "h-8"} ${dock ? "" : "border bg-card px-1 text-card-foreground shadow-sm"}`}
      >
        {fullControls && (
          <>
            <Button
              variant="ghost"
              size="icon-xs"
              className="shrink-0"
              aria-label={`${paused ? "Play" : "Pause"} ${label}`}
              title={paused ? "Play" : "Pause"}
              disabled={!canSeek}
              onClick={paused ? playback.play : playback.pause}
            >
              {paused ? (
                <PlayIcon fill="currentColor" strokeWidth={0} />
              ) : (
                <PauseIcon fill="currentColor" strokeWidth={0} />
              )}
            </Button>
            {!compact && fps !== null && (
              <>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="shrink-0"
                  aria-label={`Previous frame ${label}`}
                  title="Previous frame"
                  disabled={!canSeek}
                  onClick={() => playback.step(-1)}
                >
                  <StepBackIcon fill="currentColor" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="shrink-0"
                  aria-label={`Next frame ${label}`}
                  title="Next frame"
                  disabled={!canSeek}
                  onClick={() => playback.step(1)}
                >
                  <StepForwardIcon fill="currentColor" />
                </Button>
              </>
            )}
            <div className="min-w-7 flex-1 px-1.5">{timeline}</div>
            {!compact && (
              <span
                className={`shrink-0 px-1.5 tabular-nums whitespace-nowrap ${dock ? "text-xs" : "text-[11px]"}`}
                aria-hidden="true"
                title={`${formatTime(time)} / ${formatTime(duration)}`}
              >
                {formatTime(time)}
                {!dock && (
                  <span className="@max-[260px]:hidden text-muted-foreground">
                    {" "}
                    / {formatTime(duration)}
                  </span>
                )}
              </span>
            )}
            <Select
              value={rate}
              onValueChange={(value) => {
                if (value !== null) playback.setRate(value);
              }}
            >
              <SelectTrigger
                size="xs"
                variant="ghost"
                className={`px-[5px] text-muted-foreground [&>svg]:hidden ${dock ? "text-xs" : "text-[11px]"}`}
                aria-label={`${label} playback speed`}
                title="Playback speed"
                disabled={!canSeek}
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
              aria-label={`Loop ${label}`}
              aria-pressed={loop}
              title="Loop"
              onClick={playback.toggleLoop}
            >
              <RepeatIcon className={loop ? "" : "opacity-40"} />
            </Button>
          </>
        )}
        {playerRef && (
          <Button
            variant="ghost"
            size="icon-xs"
            className="ml-auto shrink-0"
            aria-label={`${fullscreen ? "Exit fullscreen" : "Fullscreen"} ${label}`}
            title={fullscreen ? "Exit fullscreen" : "Fullscreen"}
            disabled={!document.fullscreenEnabled}
            onClick={() => {
              const player = playerRef.current!;
              void (
                document.fullscreenElement === player
                  ? document.exitFullscreen()
                  : player.requestFullscreen()
              ).catch(() => {});
            }}
          >
            {fullscreen ? <MinimizeIcon /> : <MaximizeIcon />}
          </Button>
        )}
      </div>
      {dock && status && (
        <p role="status" className="sr-only">
          {status}
        </p>
      )}
    </div>
  );
}
