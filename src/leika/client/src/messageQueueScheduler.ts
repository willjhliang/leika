type SchedulerEnvironment<FrameHandle, TimerHandle> = {
  isHidden(): boolean;
  requestFrame(callback: () => void): FrameHandle;
  cancelFrame(handle: FrameHandle): void;
  setTimer(callback: () => void): TimerHandle;
  clearTimer(handle: TimerHandle): void;
};

/** Coalesce queue work and keep its callback valid across tab changes.
 * Returning true from run schedules the next slice without polling when idle. */
export function makeMessageQueueScheduler<FrameHandle, TimerHandle>(
  run: () => boolean | void,
  environment: SchedulerEnvironment<FrameHandle, TimerHandle>,
) {
  let stopped = false;
  let frame: FrameHandle | null = null;
  let timer: TimerHandle | null = null;

  const tick = () => {
    frame = null;
    timer = null;
    if (stopped) return;
    if (run() === true) schedule();
  };

  const schedule = () => {
    if (stopped || frame !== null || timer !== null) return;
    if (environment.isHidden()) timer = environment.setTimer(tick);
    else frame = environment.requestFrame(tick);
  };

  const visibilityChanged = () => {
    if (stopped) return;
    if (environment.isHidden() && frame !== null) {
      environment.cancelFrame(frame);
      frame = null;
      schedule();
    } else if (!environment.isHidden() && timer !== null) {
      environment.clearTimer(timer);
      timer = null;
      schedule();
    }
  };

  const stop = () => {
    stopped = true;
    if (frame !== null) environment.cancelFrame(frame);
    if (timer !== null) environment.clearTimer(timer);
    frame = null;
    timer = null;
  };

  return { schedule, visibilityChanged, stop };
}
