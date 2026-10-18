import { useEffect } from "react";
import { useViewer } from "../ViewerContext";
import type { GuiVideoControlsMessage } from "../WebsocketMessages";
import { groupPlaybackKey } from "../viewport/videoPlayback";
import { PlaybackControls } from "../viewport/PlaybackControls";
import { GuiInputRow } from "./common";

export default function VideoControls({
  uuid,
  props,
}: GuiVideoControlsMessage) {
  const viewer = useViewer();
  const key = groupPlaybackKey(props.sync_group);
  const playback = viewer.videoPlayback.get(key);
  useEffect(() => viewer.videoPlayback.retain(key), [viewer, key]);
  return (
    <GuiInputRow uuid={uuid} label={props.label} associateLabel={false}>
      <PlaybackControls playback={playback} label={props.label} />
    </GuiInputRow>
  );
}
