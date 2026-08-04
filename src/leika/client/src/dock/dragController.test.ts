import { describe, expect, it } from "vitest";

import { floatingStackGroupElements } from "./dragController";

function groupElement(groupId: string): Element {
  return {
    getAttribute: (name: string) =>
      name === "data-dock-group" ? groupId : null,
  } as unknown as Element;
}

describe("floatingStackGroupElements", () => {
  it("leaves nested area groups to the area collector and preserves stack indices", () => {
    const first = groupElement("first");
    const nestedArea = groupElement("nested-area");
    const second = groupElement("second");
    const windowElement = {
      querySelectorAll: () => [first, nestedArea, second],
    } as unknown as Element;

    const targets = floatingStackGroupElements(windowElement, [
      "first",
      "second",
    ]);

    expect(targets).toEqual([
      { element: first, index: 0 },
      { element: second, index: 1 },
    ]);
  });
});
