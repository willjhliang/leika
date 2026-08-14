import { describe, expect, it } from "vitest";

import {
  MAX_VIEWPORT_RETAINED_BYTES,
  MAX_VIEWPORT_SOURCE_CODE_UNITS,
  viewportSourceCostWithinLimits,
} from "./viewportLimits";

describe("viewport source ledger", () => {
  it("admits exact retained source boundaries and rejects each +1", () => {
    expect(
      viewportSourceCostWithinLimits({
        retainedBytes: MAX_VIEWPORT_RETAINED_BYTES,
        textCodeUnits: MAX_VIEWPORT_SOURCE_CODE_UNITS,
      }),
    ).toBe(true);
    expect(
      viewportSourceCostWithinLimits({
        retainedBytes: MAX_VIEWPORT_RETAINED_BYTES + 1,
        textCodeUnits: 0,
      }),
    ).toBe(false);
    expect(
      viewportSourceCostWithinLimits({
        retainedBytes: 0,
        textCodeUnits: MAX_VIEWPORT_SOURCE_CODE_UNITS + 1,
      }),
    ).toBe(false);
  });
});
