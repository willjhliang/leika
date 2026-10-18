// @refresh reset
import "./index.css";

import React from "react";

import { CommandPalette } from "./CommandPalette";
import ControlPanel from "./ControlPanel/ControlPanel";
import { ControlPanelFrame } from "./ControlPanel/ControlPanelFrame";
import {
  ControlPanelContext,
  useCanvasInset,
  useControlPanelSession,
} from "./ControlPanel/controlPanelLayout";
import { FilePreviewHost } from "./components/FilePreviewDialog";
import { LeikaModal } from "./Modal";
import { websocketServer } from "./SearchParamsUtils";
import { useViewer } from "./ViewerContext";
import { ViewerProvider } from "./ViewerProvider";
import { WebsocketMessageProducer } from "./WebsocketInterface";
import { Toaster } from "./components/ui/toast";
import { TooltipProvider } from "./components/ui/tooltip";
import { useAccentColor } from "./hooks/useAccentColor";
import { useColorScheme, type ColorScheme } from "./hooks/useColorScheme";
import { useMobileView } from "./hooks/useMediaQuery";
import { ViewportWorkspace } from "./viewport/ViewportWorkspace";

export function Root() {
  return (
    <ViewerProvider server={websocketServer(window.location.href)}>
      <ViewerContents>
        <WebsocketMessageProducer />
      </ViewerContents>
    </ViewerProvider>
  );
}

/** Put the scheme on `<html>`, where `index.css` and portals read it,
 * without animating every transition through the change. */
function useDocumentColorScheme(scheme: ColorScheme): void {
  React.useLayoutEffect(() => {
    const root = document.documentElement;
    const pause = document.createElement("style");
    pause.textContent = "*,*::before,*::after{transition:none!important}";
    document.head.appendChild(pause);
    root.classList.toggle("dark", scheme === "dark");
    root.style.colorScheme = scheme;
    // `theme-color` tints the browser's own chrome (the Android address bar,
    // the area around the page on iOS) to match the panel surface.
    const meta = document.querySelector<HTMLMetaElement>(
      'meta[name="theme-color"]',
    );
    const styles = getComputedStyle(root);
    if (meta !== null)
      meta.content = styles.getPropertyValue("--leika-panel-surface").trim();
    setTimeout(() => pause.remove(), 1);
  }, [scheme]);
}

function ViewerContents({ children }: { children: React.ReactNode }) {
  const viewer = useViewer();
  const controlPanel = useControlPanelSession();
  useAccentColor(viewer.useSettings((state) => state.accentColor));
  useDocumentColorScheme(useColorScheme());

  return (
    <TooltipProvider delay={500}>
      <ControlPanelContext.Provider value={controlPanel}>
        {children}
        <LeikaModal />
        <FilePreviewHost />
        <CommandPalette />
        <AppLayout />
      </ControlPanelContext.Provider>
    </TooltipProvider>
  );
}

function AppLayout() {
  const mobileView = useMobileView();
  return (
    <div className="relative flex size-full flex-col">
      <div className="relative flex w-full flex-1 overflow-hidden">
        <NotificationsPanel mobileView={mobileView} />
        <div className="relative h-full flex-1 overflow-hidden bg-background">
          {/* The desktop panel sits beside the canvas rather than around it,
              so moving it, or switching to the phone's bottom sheet, never
              remounts the workspace. */}
          <CanvasInset mobileView={mobileView}>
            <ViewportWorkspace />
          </CanvasInset>
          {!mobileView && <ControlPanelFrame />}
        </div>
        {mobileView && <ControlPanel />}
      </div>
    </div>
  );
}

/** The canvas, giving up whatever width a docked, expanded panel holds. */
function CanvasInset({
  mobileView,
  children,
}: {
  mobileView: boolean;
  children: React.ReactNode;
}) {
  const left = useCanvasInset("left", mobileView);
  const right = useCanvasInset("right", mobileView);
  return (
    <div className="absolute inset-y-0" style={{ left, right }}>
      {children}
    </div>
  );
}

function NotificationsPanel({ mobileView }: { mobileView: boolean }) {
  // The toast viewport defaults to the bottom-right corner. Leika keeps
  // notifications on the LEFT, pushed clear of a left-docked control panel so
  // they never stack underneath it. Placement is inline rather than utility
  // classes because the inset is the panel's live width; the width shrinks
  // with it so a wide docked panel can't push toasts off-screen.
  const insetPx = useCanvasInset("left", mobileView);
  return (
    <Toaster
      limit={10}
      style={{
        left: `calc(${insetPx}px + 1rem)`,
        right: "auto",
        marginInline: 0,
        width: `min(24rem, calc(100vw - ${insetPx}px - 2rem))`,
      }}
    />
  );
}
