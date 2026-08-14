// What the websocket worker counts, and how those counts become something a
// reader can act on.
//
// The counting happens in the worker because that is where the socket is: bytes
// are weighed as frames arrive and leave, before decoding, pacing, or React
// have had a chance to add their own delays to the picture. The worker keeps
// raw running totals and nothing else -- every rate, median and verdict here is
// derived on the main thread, so all of it is testable without a socket.

/** Running totals for one page's connection, as the worker sees it. */
export interface ConnectionCounters {
  /** The worker's clock when this snapshot was taken. */
  atMs: number;
  /** When the current connection opened, or null while it is down. */
  connectedSinceMs: number | null;
  /** Connections opened after the first: every one is a drop recovered from. */
  reconnects: number;
  bytesReceived: number;
  bytesSent: number;
  messagesReceived: number;
  messagesSent: number;
  /** Recent round trips in milliseconds, oldest first. Only measured while
   * someone is watching, so an empty window means "not asked yet". */
  roundTripsMs: number[];
  /** Messages the page tried to send with the socket shut. */
  droppedSends: number;
}

export function emptyCounters(atMs: number): ConnectionCounters {
  return {
    atMs,
    connectedSinceMs: null,
    reconnects: 0,
    bytesReceived: 0,
    bytesSent: 0,
    messagesReceived: 0,
    messagesSent: 0,
    roundTripsMs: [],
    droppedSends: 0,
  };
}

export type ConnectionQuality = "good" | "fair" | "poor" | "unknown";

/** Round trip at or under which the connection is called good, then fair.
 *
 * The two thresholds interaction latency is usually judged against, rather
 * than numbers picked for this panel:
 *
 * - 100ms is the limit at which a response reads as instantaneous, from
 *   Miller (1968) and Nielsen's response-time limits, and the same budget
 *   Google's RAIL model gives a UI for answering an input.
 * - 300ms is a round trip of ITU-T G.114's 150ms one-way recommendation for
 *   interactive traffic -- past it, conversation and dragging both start to
 *   feel like waiting for the other end. */
export const GOOD_ROUND_TRIP_MS = 100;
export const FAIR_ROUND_TRIP_MS = 300;

export function qualityOf(medianMs: number | null): ConnectionQuality {
  if (medianMs === null) return "unknown";
  if (medianMs <= GOOD_ROUND_TRIP_MS) return "good";
  if (medianMs <= FAIR_ROUND_TRIP_MS) return "fair";
  return "poor";
}

/** The middle value, which is what a round trip wants: one stalled reply
 * should not move the number the way an average lets it. */
export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

/** One reading of the connection, ready to display. */
export interface ConnectionReading {
  /** The most recent round trip, and the middle of the window behind it. */
  latencyMs: number | null;
  medianLatencyMs: number | null;
  quality: ConnectionQuality;
  /** Bytes per second each way, or null until two snapshots exist to
   * subtract. */
  downBytesPerSec: number | null;
  upBytesPerSec: number | null;
  bytesReceived: number;
  bytesSent: number;
  messagesReceived: number;
  messagesSent: number;
  /** How long the current connection has been up, or null while it is down. */
  connectedForMs: number | null;
  reconnects: number;
  droppedSends: number;
}

/** Read the connection from the latest counters and the ones before them.
 *
 * `previous` is optional because the first snapshot arrives alone: everything
 * cumulative is readable immediately, and the two rates fill in one snapshot
 * later rather than being guessed at from a single point. */
export function readConnection(
  current: ConnectionCounters,
  previous: ConnectionCounters | null,
): ConnectionReading {
  const elapsedSec =
    previous === null ? 0 : (current.atMs - previous.atMs) / 1000;
  // A snapshot pair from the same millisecond would divide by ~zero and report
  // a rate in the gigabytes; a pair from a restarted counter would report a
  // negative one. Neither is a rate, so neither is shown.
  const rate = (now: number, before: number): number | null => {
    if (previous === null || elapsedSec <= 0) return null;
    const delta = now - before;
    return delta < 0 ? null : delta / elapsedSec;
  };
  const roundTrips = current.roundTripsMs;
  const medianLatencyMs = median(roundTrips);
  return {
    latencyMs:
      roundTrips.length === 0 ? null : roundTrips[roundTrips.length - 1],
    medianLatencyMs,
    quality: qualityOf(medianLatencyMs),
    downBytesPerSec: rate(current.bytesReceived, previous?.bytesReceived ?? 0),
    upBytesPerSec: rate(current.bytesSent, previous?.bytesSent ?? 0),
    bytesReceived: current.bytesReceived,
    bytesSent: current.bytesSent,
    messagesReceived: current.messagesReceived,
    messagesSent: current.messagesSent,
    connectedForMs:
      current.connectedSinceMs === null
        ? null
        : Math.max(0, current.atMs - current.connectedSinceMs),
    reconnects: current.reconnects,
    droppedSends: current.droppedSends,
  };
}

const BYTE_UNITS = ["B", "kB", "MB", "GB", "TB"];

/** A size in the largest unit that leaves it above 1, to three significant
 * figures. Decimal units, because that is what a transfer rate is quoted in. */
export function formatBytes(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < BYTE_UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const decimals = unit === 0 || value >= 100 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(decimals)} ${BYTE_UNITS[unit]}`;
}

export function formatRate(bytesPerSec: number | null): string {
  return bytesPerSec === null ? "--" : `${formatBytes(bytesPerSec)}/s`;
}

/** A duration a round trip is quoted in: sub-millisecond links are real on
 * localhost, and rounding them to "0 ms" would read as a broken measurement. */
export function formatLatency(ms: number | null): string {
  if (ms === null) return "--";
  if (ms < 1) return `${ms.toFixed(2)} ms`;
  if (ms < 10) return `${ms.toFixed(1)} ms`;
  return `${Math.round(ms)} ms`;
}

/** How long the connection has been up, in the coarsest unit that still says
 * something: nobody reads seconds off a session that has run for hours. */
export function formatDuration(ms: number | null): string {
  if (ms === null) return "--";
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export const QUALITY_LABELS: Record<ConnectionQuality, string> = {
  good: "Good",
  fair: "Fair",
  poor: "Poor",
  unknown: "Measuring...",
};
