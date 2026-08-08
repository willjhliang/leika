import { describe, expect, test } from "vitest";

import { sectionAtScroll, type SectionLayout } from "./markdownSectionLayout";

const measured = (
  sections: SectionLayout["sections"],
  overrides: Partial<SectionLayout> = {},
): SectionLayout => ({
  first: sections[0]?.fragment ?? null,
  sections,
  ordered: true,
  viewportHeight: 300,
  clientHeight: 300,
  scrollHeight: 1_200,
  ...overrides,
});

/** The source-order rule used before positions were cached. */
function referenceSection(
  layout: SectionLayout,
  scrollTop: number,
): string | null {
  const line = scrollTop + 24;
  const bottom = scrollTop + layout.viewportHeight;
  const atEnd =
    layout.scrollHeight > layout.clientHeight &&
    scrollTop + layout.clientHeight >= layout.scrollHeight - 1;

  let reached = layout.first;
  let reachedTop = -Infinity;
  let topmostOnScreen: string | null = null;
  for (const section of layout.sections) {
    if (section.top <= line) {
      reached = section.fragment;
      reachedTop = section.top;
    } else if (topmostOnScreen === null && section.top < bottom) {
      topmostOnScreen = section.fragment;
    }
  }
  if (atEnd && topmostOnScreen !== null && reachedTop < scrollTop) {
    return topmostOnScreen;
  }
  return reached;
}

describe("markdown current-section selection", () => {
  test("matches the former measurement rule throughout the scroll range", () => {
    const layouts: SectionLayout[] = [
      measured([
        { fragment: "one", top: 80 },
        { fragment: "two", top: 220 },
        { fragment: "three", top: 465 },
        { fragment: "four", top: 900 },
      ]),
      measured(
        [
          { fragment: "intro", top: 0 },
          { fragment: "results", top: 400 },
          { fragment: "appendix", top: 520 },
        ],
        { scrollHeight: 600 },
      ),
      measured(
        [
          { fragment: "second", top: 100 },
          { fragment: "third", top: 500 },
        ],
        { first: "missing-first", scrollHeight: 900 },
      ),
      measured(
        [
          { fragment: "visually-last", top: 500 },
          { fragment: "visually-first", top: 100 },
          { fragment: "visually-middle", top: 300 },
        ],
        { ordered: false, scrollHeight: 800 },
      ),
    ];

    for (const layout of layouts) {
      const lastScrollTop = Math.max(
        0,
        layout.scrollHeight - layout.clientHeight,
      );
      for (let scrollTop = 0; scrollTop <= lastScrollTop; scrollTop += 1) {
        expect(sectionAtScroll(layout, scrollTop)).toBe(
          referenceSection(layout, scrollTop),
        );
      }
    }
  });

  test("uses the topmost visible short section when scrolling runs out", () => {
    const layout = measured(
      [
        { fragment: "intro", top: 0 },
        { fragment: "results", top: 400 },
        { fragment: "appendix", top: 520 },
      ],
      { scrollHeight: 600 },
    );

    // Neither short final heading can reach the ordinary 24px section line.
    // The first one still visible at the bottom is therefore current.
    expect(sectionAtScroll(layout, 300)).toBe("results");
  });

  test("does not scan every cached heading on each scroll frame", () => {
    let reads = 0;
    const sections = Array.from({ length: 8_192 }, (_, index) => {
      const section = { fragment: `section-${index}`, top: 0 };
      Object.defineProperty(section, "top", {
        enumerable: true,
        get() {
          reads += 1;
          return index * 50;
        },
      });
      return section;
    });
    const layout = measured(sections, { scrollHeight: 500_000 });

    expect(sectionAtScroll(layout, 0)).toBe("section-0");
    expect(sectionAtScroll(layout, 100_000)).toBe("section-2000");
    expect(sectionAtScroll(layout, 250_000)).toBe("section-5000");
    // Three binary searches should consume tens of cached positions, not all
    // 8,192 positions three times.
    expect(reads).toBeLessThan(100);
  });
});
