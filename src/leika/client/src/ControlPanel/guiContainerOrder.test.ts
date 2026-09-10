import { describe, expect, it } from "vitest";

import { createGuiContainerOrderSelector } from "./guiContainerOrder";

describe("GUI container order subscriptions", () => {
  it("sorts only this container and preserves membership order for tied ranks", () => {
    const select = createGuiContainerOrderSelector("panel");
    const guiUuidSetFromContainerUuid = {
      panel: { first: true, second: true },
    } as const;
    const initial = {
      guiUuidSetFromContainerUuid,
      guiOrderFromUuid: { first: 2, second: 1, elsewhere: -1 },
    };
    expect(select(initial)).toEqual(["second", "first"]);
    expect(
      select({ ...initial, guiOrderFromUuid: { first: 1, second: 1 } }),
    ).toEqual(["first", "second"]);
  });

  it("keeps the exact snapshot for unrelated containers and unchanged visual order", () => {
    const select = createGuiContainerOrderSelector("panel");
    const initial = {
      guiUuidSetFromContainerUuid: {
        panel: { first: true, second: true },
      } as const,
      guiOrderFromUuid: { first: 1, second: 2 },
    };
    const ordered = select(initial);
    expect(select(initial)).toBe(ordered);
    expect(
      select({
        ...initial,
        guiUuidSetFromContainerUuid: {
          ...initial.guiUuidSetFromContainerUuid,
          other: { third: true },
        },
        guiOrderFromUuid: { ...initial.guiOrderFromUuid, third: 0 },
      }),
    ).toBe(ordered);
    // A server may renumber ranks without moving any controls.
    expect(
      select({ ...initial, guiOrderFromUuid: { first: 3, second: 4 } }),
    ).toBe(ordered);
  });

  it("invalidates only containers whose rendered child list changes", () => {
    const selectors = Array.from({ length: 100 }, (_, index) =>
      createGuiContainerOrderSelector(`panel-${index}`),
    );
    const guiUuidSetFromContainerUuid = Object.fromEntries(
      selectors.map((_, index) => [
        `panel-${index}`,
        { [`child-${index}`]: true as const },
      ]),
    );
    const guiOrderFromUuid = Object.fromEntries(
      selectors.map((_, index) => [`child-${index}`, 0]),
    );
    const before = { guiUuidSetFromContainerUuid, guiOrderFromUuid };
    const snapshots = selectors.map((select) => select(before));
    const after = {
      guiUuidSetFromContainerUuid: {
        ...guiUuidSetFromContainerUuid,
        "panel-0": { "child-0": true as const, added: true as const },
      },
      guiOrderFromUuid: { ...guiOrderFromUuid, added: 1 },
    };
    expect(
      selectors.filter((select, index) => select(after) !== snapshots[index]),
    ).toHaveLength(1);
    expect(selectors[0](after)).toEqual(["child-0", "added"]);
  });

  it("handles removal, reset, recreation and prototype-named ids", () => {
    const select = createGuiContainerOrderSelector("panel");
    const state = {
      guiUuidSetFromContainerUuid: JSON.parse(
        '{"panel":{"__proto__":true,"constructor":true}}',
      ),
      guiOrderFromUuid: JSON.parse('{"__proto__":2,"constructor":1}'),
    };
    expect(select(state)).toEqual(["constructor", "__proto__"]);
    const cleared = select({
      guiUuidSetFromContainerUuid: {},
      guiOrderFromUuid: {},
    });
    expect(cleared).toEqual([]);
    expect(
      select({
        guiUuidSetFromContainerUuid: { panel: {} },
        guiOrderFromUuid: {},
      }),
    ).toBe(cleared);
    expect(select(state)).toEqual(["constructor", "__proto__"]);
  });
});
