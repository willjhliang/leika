import { useEffect } from "react";
import { useViewer } from "../ViewerContext";
import type { GuiVideoControlsMessage } from "../WebsocketMessages";
import { groupPlaybackKey } from "../viewport/videoPlayback";
import { VideoPlaybackControls } from "../viewport/VideoPlaybackControls";

export default function VideoControls({ props }: GuiVideoControlsMessage) {
  const viewer = useViewer();
  const key = groupPlaybackKey(props.sync_group);
  const playback = viewer.videoPlayback.get(key);
  useEffect(() => viewer.videoPlayback.retain(key), [viewer, key]);
  return (
    <div className="min-w-0">
      <div className="mb-1 text-xs font-medium">{props.label}</div>
      <VideoPlaybackControls playback={playback} label={props.label} />
    </div>
  );
}
