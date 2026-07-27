import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  CLIENT_SETTINGS_STORAGE_KEY,
  ClientSettings,
  ClientSettingsActions,
  ClientSettingsStorage,
  defaultClientSettings,
  readClientSettings,
  useClientSettings,
} from "./ClientSettings";

class MemoryStorage implements ClientSettingsStorage {
  readonly values = new Map<string, string>();
  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

class ThrowingStorage implements ClientSettingsStorage {
  getItem(): string | null {
    throw new Error("storage unavailable");
  }
  setItem(): void {
    throw new Error("storage unavailable");
  }
}

function stored(storage: MemoryStorage, settings: Partial<ClientSettings>) {
  storage.values.set(CLIENT_SETTINGS_STORAGE_KEY, JSON.stringify(settings));
}

function createSettingsHarness(storage: ClientSettingsStorage | null): {
  actions: ClientSettingsActions;
  getState: () => ClientSettings;
} {
  let settings: ReturnType<typeof useClientSettings> | undefined;
  function Harness(): React.ReactNode {
    settings = useClientSettings(storage);
    return null;
  }
  renderToStaticMarkup(React.createElement(Harness));
  if (settings === undefined)
    throw new Error("Settings harness did not render");
  return { actions: settings.actions, getState: settings.store.get };
}

describe("readClientSettings", () => {
  it("defaults to following the server with no accent and hidden titles", () => {
    expect(readClientSettings(new MemoryStorage())).toEqual({
      darkMode: null,
      showPaneTitles: false,
      accentColor: null,
    });
    expect(readClientSettings(null)).toEqual(defaultClientSettings());
  });

  it("restores a stored payload", () => {
    const storage = new MemoryStorage();
    stored(storage, {
      darkMode: true,
      showPaneTitles: true,
      accentColor: "rgb(10, 20, 30)",
    });
    expect(readClientSettings(storage)).toEqual({
      darkMode: true,
      showPaneTitles: true,
      accentColor: "rgb(10, 20, 30)",
    });
  });

  it("keeps the fields a partial payload does carry", () => {
    const storage = new MemoryStorage();
    stored(storage, { showPaneTitles: true });
    expect(readClientSettings(storage)).toEqual({
      darkMode: null,
      showPaneTitles: true,
      accentColor: null,
    });
  });

  it("drops fields stored with the wrong type", () => {
    const storage = new MemoryStorage();
    storage.values.set(
      CLIENT_SETTINGS_STORAGE_KEY,
      JSON.stringify({ darkMode: "yes", showPaneTitles: 1, accentColor: 7 }),
    );
    expect(readClientSettings(storage)).toEqual(defaultClientSettings());
  });

  it("drops an accent that no longer parses as a color", () => {
    const storage = new MemoryStorage();
    stored(storage, { darkMode: true, accentColor: "chartreuse-ish" });
    expect(readClientSettings(storage)).toEqual({
      darkMode: true,
      showPaneTitles: false,
      accentColor: null,
    });
  });

  it("falls back when the payload is not an object or not JSON", () => {
    const storage = new MemoryStorage();
    storage.values.set(CLIENT_SETTINGS_STORAGE_KEY, "{not json");
    expect(readClientSettings(storage)).toEqual(defaultClientSettings());
    storage.values.set(CLIENT_SETTINGS_STORAGE_KEY, "null");
    expect(readClientSettings(storage)).toEqual(defaultClientSettings());
    storage.values.set(CLIENT_SETTINGS_STORAGE_KEY, '"dark"');
    expect(readClientSettings(storage)).toEqual(defaultClientSettings());
  });

  it("falls back when reading throws", () => {
    expect(readClientSettings(new ThrowingStorage())).toEqual(
      defaultClientSettings(),
    );
  });
});

describe("useClientSettings", () => {
  it("writes every change back under one key", () => {
    const storage = new MemoryStorage();
    const { actions, getState } = createSettingsHarness(storage);

    actions.setDarkMode(true);
    actions.setShowPaneTitles(true);
    actions.setAccentColor("rgb(255, 0, 0)");

    expect(getState()).toEqual({
      darkMode: true,
      showPaneTitles: true,
      accentColor: "rgb(255, 0, 0)",
    });
    expect(storage.values.size).toBe(1);
    expect(
      JSON.parse(storage.values.get(CLIENT_SETTINGS_STORAGE_KEY)!),
    ).toEqual(getState());
  });

  it("restores what a previous session stored", () => {
    const storage = new MemoryStorage();
    createSettingsHarness(storage).actions.setDarkMode(false);
    expect(createSettingsHarness(storage).getState().darkMode).toBe(false);
  });

  it("stores a reset accent as the default rather than dropping the key", () => {
    const storage = new MemoryStorage();
    const { actions } = createSettingsHarness(storage);
    actions.setAccentColor("rgb(1, 2, 3)");
    actions.setAccentColor(null);
    expect(readClientSettings(storage).accentColor).toBeNull();
  });

  it("stays usable when storage is absent or refuses writes", () => {
    for (const storage of [null, new ThrowingStorage()]) {
      const { actions, getState } = createSettingsHarness(storage);
      actions.setShowPaneTitles(true);
      expect(getState().showPaneTitles).toBe(true);
    }
  });
});
