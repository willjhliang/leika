import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import type {
  GuiPlaybackMessage,
  GuiPlaybackCommandMessage,
} from "../WebsocketMessages";
import { PlaybackControls } from "../viewport/PlaybackControls";
import { GuiInputRow } from "./common";

/** A controlled view: Python publishes time; the browser sends only user intent. */
export default function Playback({ uuid, props }: GuiPlaybackMessage) {
  const { messageSender } = useGuiComponent();
  const send = (action: GuiPlaybackCommandMessage["action"], value = 0) =>
    messageSender(
      { type: "GuiPlaybackCommandMessage", uuid, action, value },
      { coalesce: false },
    );
  const playback = {
    state: () => ({
      time: props.time,
      duration: props.duration,
      paused: !props.playing,
      rate: props.speed,
      loop: props.loop,
      fps: props.fps,
      buffering: props.buffering,
      error: false,
    }),
    play: () => send("play"),
    pause: () => send("pause"),
    seek: (time: number) => send("seek", time),
    step: (direction: number) => send("step", direction),
    setRate: (speed: number) => send("speed", speed),
    toggleLoop: () => send("loop"),
  };
  return (
    <GuiInputRow
      uuid={uuid}
      label={props.label}
      associateLabel={false}
      disabled={props.disabled}
    >
      <PlaybackControls
        playback={playback}
        label={props.label}
        disabled={props.disabled}
        statusText={props.buffering ? "Preparing content…" : undefined}
      />
    </GuiInputRow>
  );
}
