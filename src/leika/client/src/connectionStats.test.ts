import { describe, expect, it } from "vitest";

import {
  ConnectionCounters,
  emptyCounters,
  formatBytes,
  formatDuration,
  formatLatency,
  formatRate,
  median,
  qualityOf,
  readConnection,
} from "./connectionStats";

function counters(overrides: Partial<ConnectionCounters>): ConnectionCounters {
  return { ...emptyCounters(0), ...overrides };
}

describe("median", () => {
  it("takes the middle of an odd window and the mean of an even one", () => {
    expect(median([5, 1, 3])).toBe(3);
    expect(median([1, 2, 3, 4])).toBe(2.5);
    expect(median([])).toBeNull();
  });

  it("is unmoved by one stalled reply", () => {
    // The reason it is not an average: a single 4-second round trip in a
    // window of fast ones must not make the link look broken.
    expect(median([10, 12, 11, 4000, 13])).toBe(12);
  });

  it("leaves the samples it was given alone", () => {
    const samples = [3, 1, 2];
    median(samples);
    expect(samples).toEqual([3, 1, 2]);
  });
});

describe("qualityOf", () => {
  it("reads a round trip against the usual interaction limits", () => {
    // 100ms is where a response stops reading as instantaneous, and 300ms is
    // a round trip of the 150ms one-way limit interactive traffic is held to.
    expect(qualityOf(5)).toBe("good");
    expect(qualityOf(100)).toBe("good");
    expect(qualityOf(101)).toBe("fair");
    expect(qualityOf(300)).toBe("fair");
    expect(qualityOf(301)).toBe("poor");
  });

  it("says nothing at all when nothing has been measured", () => {
    // Not "good": an unmeasured link is not a fast one.
    expect(qualityOf(null)).toBe("unknown");
  });
});

describe("readConnection", () => {
  const first = counters({
    atMs: 1000,
    bytesReceived: 500,
    bytesSent: 100,
    connectedSinceMs: 0,
  });

  it("has no rate to report from one snapshot", () => {
    const reading = readConnection(first, null);
    expect(reading.downBytesPerSec).toBeNull();
    expect(reading.upBytesPerSec).toBeNull();
    // The cumulative numbers are readable straight away, though.
    expect(reading.bytesReceived).toBe(500);
    expect(reading.connectedForMs).toBe(1000);
  });

  it("divides the difference by the time between snapshots", () => {
    const second = counters({
      atMs: 3000,
      bytesReceived: 2500,
      bytesSent: 300,
      connectedSinceMs: 0,
    });
    const reading = readConnection(second, first);
    expect(reading.downBytesPerSec).toBe(1000);
    expect(reading.upBytesPerSec).toBe(100);
  });

  it("refuses a rate it cannot divide, rather than reporting infinity", () => {
    const sameInstant = counters({ atMs: 1000, bytesReceived: 900 });
    expect(readConnection(sameInstant, first).downBytesPerSec).toBeNull();
  });

  it("refuses a rate from counters that went backwards", () => {
    // A worker restarted under a page that kept its last snapshot: the totals
    // begin again, and the difference is negative rather than slow.
    const restarted = counters({ atMs: 3000, bytesReceived: 20 });
    expect(readConnection(restarted, first).downBytesPerSec).toBeNull();
  });

  it("reports the last round trip beside the middle of the window", () => {
    const reading = readConnection(
      counters({ atMs: 1000, roundTripsMs: [10, 12, 400] }),
      null,
    );
    expect(reading.latencyMs).toBe(400);
    expect(reading.medianLatencyMs).toBe(12);
    // The verdict follows the median, so one slow reply does not condemn it.
    expect(reading.quality).toBe("good");
  });

  it("has no uptime while the connection is down", () => {
    const down = counters({ atMs: 5000, connectedSinceMs: null });
    expect(readConnection(down, null).connectedForMs).toBeNull();
  });
});

describe("formatting", () => {
  it("scales bytes to the unit that keeps them readable", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(999)).toBe("999 B");
    expect(formatBytes(1000)).toBe("1.00 kB");
    expect(formatBytes(15_400)).toBe("15.4 kB");
    expect(formatBytes(999_000)).toBe("999 kB");
    expect(formatBytes(2_500_000)).toBe("2.50 MB");
  });

  it("keeps sub-millisecond round trips visible", () => {
    // Rounding a localhost link to "0 ms" would read as a broken measurement.
    expect(formatLatency(0.42)).toBe("0.42 ms");
    expect(formatLatency(3.14)).toBe("3.1 ms");
    expect(formatLatency(87.6)).toBe("88 ms");
    expect(formatLatency(null)).toBe("--");
  });

  it("says nothing rather than zero when there is no rate yet", () => {
    expect(formatRate(null)).toBe("--");
    expect(formatRate(2048)).toBe("2.05 kB/s");
  });

  it("drops to the coarsest unit that still says something", () => {
    expect(formatDuration(4_000)).toBe("4s");
    expect(formatDuration(95_000)).toBe("1m 35s");
    expect(formatDuration(7_800_000)).toBe("2h 10m");
    expect(formatDuration(null)).toBe("--");
  });
});
