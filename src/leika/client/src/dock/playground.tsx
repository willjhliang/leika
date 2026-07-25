// Dev-only playground for the docking library. Served by the Vite dev server
// at /dock_test.html; not part of the production bundle (which only inputs
// index.html). Run `vite` and open http://localhost:3000/dock_test.html.

/* eslint-disable react-refresh/only-export-components -- standalone dev entry. */
// Uses the same base typography as the app (Geist font from index.css) so the
// dock's fonts and shadows look right here.
import "../index.css";
import { GripVerticalIcon } from "lucide-react";
import React from "react";
import ReactDOM from "react-dom/client";
import { Button } from "../components/ui/button";
import { TooltipProvider } from "../components/ui/tooltip";
import { DockArea } from "./DockArea";
import { useDock } from "./DockContext";
import { DockManager } from "./DockManager";
import { makeGroup } from "./layoutOps";
import { DockLayout, PanelRegistry, TabGroup } from "./types";

// A generic titled header for an unmergeable panel, used to exercise the
// full-width-header code path (as opposed to a tab). Intentionally NOT a copy
// of the real control-panel title bar: the playground demonstrates the dock
// library in isolation, so it must not depend on -- or drift against -- the
// app's actual panel chrome. The action button is inert (stopPropagation so a
// click doesn't start a panel drag).
function DemoHeader({ label }: { label: string }) {
  const stop = (event: React.PointerEvent | React.MouseEvent) =>
    event.stopPropagation();
  return (
    <div className="flex w-full items-center gap-2">
      <span className="flex-1 font-medium">{label}</span>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label="Demo action"
        onPointerDown={stop}
        onClick={stop}
      >
        <GripVerticalIcon />
      </Button>
    </div>
  );
}

// A handful of demo panels with throwaway content.
function demoBody(label: string, lines: number) {
  return (
    <div>
      {Array.from({ length: lines }, (_, i) => (
        <p key={i} className="text-sm text-muted-foreground">
          {label} - line {i + 1}
        </p>
      ))}
    </div>
  );
}

// Inner panels available to drop into the nested dockable areas.
const panels: PanelRegistry = {
  scene: {
    id: "scene",
    title: "Scene",
    // A normal panel hosting a nested dockable area. Drag any panel (floating or
    // docked) onto the area to add it as a tab; drag an area tab out to float it
    // or merge it with this (the parent) panel.
    render: () => (
      <div>
        {demoBody("Scene", 3)}
        <p className="text-xs font-medium">
          Nested dockable area (normal panel):
        </p>
        <DockArea areaId="area-scene" inheritContentPadding />
      </div>
    ),
  },
  controls: {
    id: "controls",
    title: "Controls",
    render: () => demoBody("Controls", 12),
  },
  inspector: {
    id: "inspector",
    title: "Inspector",
    render: () => demoBody("Inspector", 6),
  },
  console: {
    id: "console",
    title: "Console",
    render: () => demoBody("Console", 20),
  },
  // The "main" panel: an UNMERGEABLE panel with a full-width custom header
  // (exercises the header path -- its label shows as a header, not a tab),
  // nothing can be merged into it, and it hosts a nested dockable area.
  monitor: {
    id: "monitor",
    title: "Main",
    titleNode: <DemoHeader label="Main" />,
    unmergeable: true,
    // The whole body is a single full-bleed nested area (no padding, fills the
    // panel) -- there is nothing else in this panel.
    fullBleed: true,
    render: () => <DockArea areaId="area-main" fill />,
  },
  // Inner panels: ordinary panels that happen to start inside nested areas.
  // There is no difference between these and the "standard" panels above.
  layers: {
    id: "layers",
    title: "Layers",
    render: () => demoBody("Layers", 5),
  },
  props: {
    id: "props",
    title: "Properties",
    render: () => demoBody("Properties", 7),
  },
  history: {
    id: "history",
    title: "History",
    render: () => demoBody("History", 4),
  },
};

// Build the initial layout: a few floating panels, one already-docked panel, and
// two nested dockable areas (each backed by a flat tab group in `groups`).
const dockedGroup: TabGroup = makeGroup(["scene"]);
const floatA: TabGroup = makeGroup(["controls"]);
const floatB: TabGroup = makeGroup(["inspector"]);
const floatC: TabGroup = makeGroup(["console"]);
const floatM: TabGroup = makeGroup(["monitor"]);
// Area-backing groups (flat tabs). Their panels start docked inside the areas.
const areaSceneGroup: TabGroup = makeGroup(["layers"]);
const areaMainGroup: TabGroup = makeGroup(["props", "history"]);

const initialLayout: DockLayout = {
  groups: {
    [dockedGroup.id]: dockedGroup,
    [floatA.id]: floatA,
    [floatB.id]: floatB,
    [floatC.id]: floatC,
    [floatM.id]: floatM,
    [areaSceneGroup.id]: areaSceneGroup,
    [areaMainGroup.id]: areaMainGroup,
  },
  docked: {
    left: { type: "leaf", id: "n-docked", group: dockedGroup.id, weight: 1 },
    right: null,
  },
  floating: [
    { id: "w-a", x: 360, y: 40, width: 280, stack: [floatA.id] },
    { id: "w-b", x: 680, y: 120, width: 260, stack: [floatB.id] },
    { id: "w-c", x: 480, y: 320, width: 300, stack: [floatC.id] },
    { id: "w-m", x: 900, y: 60, width: 300, height: 380, stack: [floatM.id] },
  ],
  areas: {
    "area-scene": { id: "area-scene", group: areaSceneGroup.id },
    "area-main": { id: "area-main", group: areaMainGroup.id },
  },
};

// Test probe (write side, pairing with the onLayoutChange read probe below):
// window.__dockSetLayout(layout) replaces the layout MODEL directly, so e2e
// suites can inject a starting arrangement instead of building it from long
// chains of setup drags. Rendered inside the DockManager subtree so the
// injection goes through useDock().api.apply -> the manager's applyOp, which
// reconciles docked region widths exactly like a real gesture (top-level
// column weights are rewritten to pixel widths; new columns get the default).
// Injected layouts should reference the registered panel ids above and use a
// distinctive prefix (tests use "t-") for node/group/window ids so they never
// collide with freshId-generated ones. Test-only globals stay confined to
// this playground; the library itself exposes nothing on window.
function LayoutInjector() {
  const { api } = useDock();
  React.useEffect(() => {
    const probe = window as unknown as {
      __dockSetLayout?: (layout: DockLayout) => void;
    };
    probe.__dockSetLayout = (layout) => api.apply(() => layout);
    return () => {
      delete probe.__dockSetLayout;
    };
  }, [api]);
  return null;
}

function Playground() {
  // Match the main page: presence of ?darkMode flips to dark.
  const darkMode =
    new URLSearchParams(window.location.search).get("darkMode") !== null;
  React.useLayoutEffect(() => {
    document.documentElement.classList.toggle("dark", darkMode);
    document.documentElement.classList.toggle("light", !darkMode);
  }, [darkMode]);
  return (
    <TooltipProvider>
      <div className="h-screen w-screen">
        <DockManager
          initialLayout={initialLayout}
          panels={panels}
          // Test probe: e2e suites read the committed layout model directly
          // (DOM scans miss panels whose host tab is inactive, e.g. tabs inside
          // a nested area when the area's host panel body is hidden).
          onLayoutChange={(l) => {
            (window as unknown as { __dockLayout: unknown }).__dockLayout = l;
          }}
        >
          <LayoutInjector />
          {/* Stand-in for the pane workspace, matching the Leika background. */}
          <div className="flex size-full items-center justify-center bg-background text-sm text-muted-foreground">
            canvas area
          </div>
        </DockManager>
      </div>
    </TooltipProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <Playground />
  </React.StrictMode>,
);
