/** Whether a retry should start a new socket instead of leaving this one alone. */
export function shouldRetryWebsocket(readyState: number | null): boolean {
  return (
    readyState === null ||
    readyState === WebSocket.CLOSING ||
    readyState === WebSocket.CLOSED
  );
}
