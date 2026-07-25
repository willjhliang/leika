import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  commandPalette,
  getCommandPaletteOpen,
  subscribeCommandPalette,
} from "./CommandPaletteController";

describe("commandPalette", () => {
  beforeEach(() => commandPalette.close());
  afterEach(() => commandPalette.close());

  it("publishes imperative open, close, and toggle changes", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeCommandPalette(listener);

    commandPalette.open();
    expect(getCommandPaletteOpen()).toBe(true);
    expect(listener).toHaveBeenLastCalledWith(true);

    commandPalette.toggle();
    expect(getCommandPaletteOpen()).toBe(false);
    expect(listener).toHaveBeenLastCalledWith(false);

    commandPalette.open();
    commandPalette.close();
    expect(getCommandPaletteOpen()).toBe(false);
    expect(listener).toHaveBeenLastCalledWith(false);

    unsubscribe();
    listener.mockClear();
    commandPalette.open();
    expect(listener).not.toHaveBeenCalled();
  });
});
