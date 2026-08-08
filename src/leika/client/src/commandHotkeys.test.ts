import { describe, expect, it, vi } from "vitest";

import { commandPaletteHotkeys, hotkeyMatches } from "./commandHotkeys";

describe("commandPaletteHotkeys", () => {
  it("returns no bindings when there are no commands", () => {
    expect(commandPaletteHotkeys(false, vi.fn(), [])).toEqual([]);
  });

  it("prepends palette shortcuts when commands are available", () => {
    const open = vi.fn();
    const trigger = vi.fn();
    const bindings = commandPaletteHotkeys(true, open, [["shift+x", trigger]]);

    expect(bindings.map(([definition]) => definition)).toEqual([
      "mod+k",
      "mod+shift+p",
      "shift+x",
    ]);
    expect(bindings[0][1]).toBe(open);
    expect(bindings[2][1]).toBe(trigger);
  });
});

describe("hotkeyMatches", () => {
  const event = (
    overrides: Partial<{
      key: string;
      ctrlKey: boolean;
      metaKey: boolean;
      shiftKey: boolean;
      altKey: boolean;
    }> = {},
  ) => ({
    key: "k",
    ctrlKey: false,
    metaKey: false,
    shiftKey: false,
    altKey: false,
    ...overrides,
  });

  it("accepts either platform modifier for mod shortcuts", () => {
    expect(hotkeyMatches(event({ ctrlKey: true }), "mod+k")).toBe(true);
    expect(hotkeyMatches(event({ metaKey: true }), "mod+k")).toBe(true);
  });

  it("requires the exact non-modifier key set", () => {
    expect(hotkeyMatches(event({ key: "x", shiftKey: true }), "shift+x")).toBe(
      true,
    );
    expect(
      hotkeyMatches(
        event({ key: "x", shiftKey: true, altKey: true }),
        "shift+x",
      ),
    ).toBe(false);
  });
});
