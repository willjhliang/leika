import { describe, expect, it, vi } from "vitest";

import { randomUuid } from "./randomUuid";

describe("randomUuid", () => {
  it("uses native randomUUID when it is available", () => {
    const randomUUID = vi.fn(() => "native-uuid");
    const getRandomValues = vi.fn((array: Uint8Array) => array);

    expect(randomUuid({ randomUUID, getRandomValues })).toBe("native-uuid");
    expect(randomUUID).toHaveBeenCalledOnce();
    expect(getRandomValues).not.toHaveBeenCalled();
  });

  it("creates an RFC 4122 version 4 UUID from getRandomValues", () => {
    const getRandomValues = (array: Uint8Array) => {
      array.forEach((_, index) => {
        array[index] = index;
      });
      return array;
    };

    expect(randomUuid({ getRandomValues })).toBe(
      "00010203-0405-4607-8809-0a0b0c0d0e0f",
    );
  });
});
