import { describe, expect, it } from "vitest";

import {
  createFloatingStackResizeSession,
  floatingStackCellBudget,
} from "./floatingStackResize";

type ResizeSessionArgs = Parameters<typeof createFloatingStackResizeSession>[0];

function session(
  fixedHeight: boolean,
  containerPx = 200,
  overrides: Partial<ResizeSessionArgs> = {},
) {
  return createFloatingStackResizeSession({
    stack: ["a", "b"],
    weights: [1, 1],
    collapsed: [false, false],
    containerPx,
    dividerIndex: 0,
    minCell: 60,
    fixedHeight,
    ...overrides,
  });
}

describe("floatingStackCellBudget", () => {
  it("subtracts every divider and collapsed-row pixel from the flex budget", () => {
    expect(floatingStackCellBudget(300, [7, 7], [36])).toBe(250);
  });

  it("floors an overcommitted stack at zero", () => {
    expect(floatingStackCellBudget(40, [14], [36])).toBe(0);
  });
});

describe("createFloatingStackResizeSession", () => {
  it("does not pin auto-height when no effective resize occurred", () => {
    const resize = session(false);

    expect(resize.applyDelta(0)).toBeNull();
    expect(resize.rollback()).toEqual({
      groupIds: ["a", "b"],
      stackWeights: undefined,
      restoreAutoHeight: false,
    });
  });

  it("does not pin when a movement is fully blocked by minimum sizes", () => {
    const resize = session(false, 120);

    expect(resize.applyDelta(-100)).toBeNull();
    expect(resize.rollback().restoreAutoHeight).toBe(false);
  });

  it("pins once on the first effective auto-height resize and fully rolls back", () => {
    const resize = session(false);

    expect(resize.applyDelta(20)).toEqual({
      weights: { a: 120, b: 80 },
      pinAutoHeight: true,
    });
    expect(resize.applyDelta(10)).toEqual({
      weights: { a: 110, b: 90 },
      pinAutoHeight: false,
    });
    expect(resize.rollback()).toEqual({
      groupIds: ["a", "b"],
      stackWeights: undefined,
      restoreAutoHeight: true,
    });
  });

  it("never requests height restoration for an initially fixed window", () => {
    const resize = session(true);

    expect(resize.applyDelta(20)?.pinAutoHeight).toBe(false);
    expect(resize.rollback().restoreAutoHeight).toBe(false);
  });

  it("captures the stored map without materializing default weights", () => {
    const resize = session(true, 200, {
      weights: [2, 1],
      stackWeights: { a: 2 },
    });

    expect(resize.applyDelta(20)).not.toBeNull();
    expect(resize.rollback()).toEqual({
      groupIds: ["a", "b"],
      stackWeights: { a: 2 },
      restoreAutoHeight: false,
    });
  });

  it("conserves the rendered total when fixed chrome is excluded", () => {
    const cellBudget = floatingStackCellBudget(300, [7, 7], [36]);
    const resize = createFloatingStackResizeSession({
      stack: ["a", "b", "c"],
      weights: [1, 1, 1],
      collapsed: [false, true, false],
      containerPx: cellBudget,
      dividerIndex: 0,
      minCell: 60,
      fixedHeight: true,
    });

    const update = resize.applyDelta(20);
    expect(update).toEqual({
      weights: { a: 145, c: 105 },
      pinAutoHeight: false,
    });
    expect(update!.weights.a + update!.weights.c + 7 + 7 + 36).toBe(300);
  });

  it("resizes through a collapsed right neighbor", () => {
    const resize = createFloatingStackResizeSession({
      stack: ["a", "b", "c"],
      weights: [1, 1, 1],
      collapsed: [false, true, false],
      containerPx: 300,
      dividerIndex: 0,
      minCell: 60,
      fixedHeight: true,
    });

    expect(resize.applyDelta(20)).toEqual({
      weights: { a: 170, c: 130 },
      pinAutoHeight: false,
    });
  });

  it("resizes through a collapsed left neighbor", () => {
    const resize = createFloatingStackResizeSession({
      stack: ["a", "b", "c"],
      weights: [1, 1, 1],
      collapsed: [false, true, false],
      containerPx: 300,
      dividerIndex: 1,
      minCell: 60,
      fixedHeight: true,
    });

    expect(resize.applyDelta(-20)).toEqual({
      weights: { a: 130, c: 170 },
      pinAutoHeight: false,
    });
  });
});
