import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { createKeyedStore } from "./store";

type Pair = { left: string; right: string };

const selectLeft = (pair: Pair | undefined) => pair?.left ?? "missing";
const selectRight = (pair: Pair | undefined) => pair?.right ?? "missing";

describe("createKeyedStore", () => {
  it("re-evaluates a changed selector when the key and version are unchanged", () => {
    const store = createKeyedStore<Pair>({
      item: { left: "left", right: "right" },
    });

    function Harness() {
      const [right, setRight] = React.useState(false);
      const selected = store("item", right ? selectRight : selectLeft);
      if (!right) setRight(true);
      return selected;
    }

    expect(renderToStaticMarkup(React.createElement(Harness))).toBe("right");
  });

  it("uses the current equality function after selection inputs change", () => {
    const store = createKeyedStore({ item: 1 });
    const selectOne = () => ({ value: 1 });
    const selectTwo = () => ({ value: 2 });
    const keepPrevious = () => true;
    const replacePrevious = () => false;

    function Harness() {
      const [second, setSecond] = React.useState(false);
      const selected = store(
        "item",
        second ? selectTwo : selectOne,
        second ? replacePrevious : keepPrevious,
      );
      if (!second) setSecond(true);
      return String(selected.value);
    }

    expect(renderToStaticMarkup(React.createElement(Harness))).toBe("2");
  });

  it("retains the selected reference when the equality function matches", () => {
    const store = createKeyedStore({ item: 1 });
    const selectFirst = () => ({ value: 1 });
    const selectEquivalent = () => ({ value: 1 });
    const selectedValues: { value: number }[] = [];

    function Harness() {
      const [equivalent, setEquivalent] = React.useState(false);
      const selected = store(
        "item",
        equivalent ? selectEquivalent : selectFirst,
        (left, right) => left.value === right.value,
      );
      selectedValues.push(selected);
      if (!equivalent) setEquivalent(true);
      return null;
    }

    renderToStaticMarkup(React.createElement(Harness));
    expect(selectedValues.length).toBeGreaterThanOrEqual(2);
    expect(selectedValues.at(-1)).toBe(selectedValues[0]);
  });
});
