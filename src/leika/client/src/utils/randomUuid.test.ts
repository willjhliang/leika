import { describe, expect, it } from "vitest";

import { randomUuid } from "./randomUuid";

describe("randomUuid", () => {
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
