export interface PlaybackState {
  time: number;
  duration: number;
  paused: boolean;
  rate: number;
  loop: boolean;
  fps: number | null;
  buffering: boolean;
  error: boolean;
}

export interface PlaybackController {
  state: () => PlaybackState;
  play: () => void;
  pause: () => void;
  seek: (time: number) => void;
  step: (direction: number) => void;
  setRate: (rate: number) => void;
  toggleLoop: () => void;
}
