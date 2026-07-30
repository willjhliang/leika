/** Rate smoothing for incoming message batches.
 *
 * A server streaming updates sends on its own rhythm, but network jitter
 * bunches the arrivals. Delivering each batch at the moment it arrives makes
 * streamed values visibly stutter; delivering on the server's own timestamps
 * replays the rhythm. A batch is delayed only while the stream is dense and
 * the client is keeping up -- the first batch, a slow stream, or a client
 * behind real time all flush immediately.
 */
export type PacingState = {
  prevPythonTimestampMs?: number;
  lastIdealJsMs?: number;
  /** Running minimum, as the best estimate of true clock offset. */
  jsTimeMinusPythonTime: number;
};

export function newPacingState(): PacingState {
  return { jsTimeMinusPythonTime: Infinity };
}

/** How long to hold a batch before delivering it, in ms (0 = deliver now).
 * Mutates `state` with the delivery it schedules. */
export function paceBatch(
  state: PacingState,
  receivedMs: number,
  nowMs: number,
  pythonTimestampMs: number,
): number {
  state.jsTimeMinusPythonTime = Math.min(
    receivedMs - pythonTimestampMs,
    state.jsTimeMinusPythonTime,
  );
  const pythonTimeDeltaMs =
    pythonTimestampMs - (state.prevPythonTimestampMs ?? pythonTimestampMs);
  state.prevPythonTimestampMs = pythonTimestampMs;

  if (
    // First batch, or a gap wide enough that exact timing cannot matter.
    state.lastIdealJsMs === undefined ||
    pythonTimeDeltaMs > 100 ||
    // More than 100ms behind real time: catch up rather than smooth.
    nowMs - state.jsTimeMinusPythonTime - pythonTimestampMs > 100
  ) {
    state.lastIdealJsMs = nowMs;
    return 0;
  }

  const timeUntilIdealJsMs = state.lastIdealJsMs + pythonTimeDeltaMs - nowMs;
  if (timeUntilIdealJsMs > 3) {
    // Early, meaning the previous batch ran late. The damping bleeds that
    // debt off over several batches instead of stalling this one fully.
    const dampingFactor = 0.95;
    state.lastIdealJsMs += pythonTimeDeltaMs * dampingFactor;
    return timeUntilIdealJsMs * dampingFactor;
  }
  state.lastIdealJsMs = nowMs;
  return 0;
}
