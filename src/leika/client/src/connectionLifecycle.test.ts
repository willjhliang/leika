import { describe, expect, it } from "vitest";

import { resetConnectionOwners } from "./connectionLifecycle";

describe("resetConnectionOwners", () => {
  it("drops viewport owners before resetting their shared resources", () => {
    const events: string[] = [];
    let retainedPanes = ["image", "plotly", "viser"];

    resetConnectionOwners({
      resetGui: () => {
        events.push("gui");
      },
      resetPanes: () => {
        events.push("panes");
        retainedPanes = [];
      },
      resetResources: () => {
        expect(retainedPanes).toEqual([]);
        events.push("resources");
      },
    });

    expect(events).toEqual(["gui", "panes", "resources"]);
    expect(retainedPanes).toEqual([]);
  });
});
