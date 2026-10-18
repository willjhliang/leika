// @refresh reset
import "./index.css";

import React from "react";
import { ThemeProvider as NextThemesProvider } from "next-themes";

import { CommandPalette } from "./CommandPalette";
import ControlPanel from "./ControlPanel/ControlPanel";
import { ControlPanelFrame } from "./ControlPanel/ControlPanelFrame";
import {
  ControlPanelContext,
  useCanvasInset,
  useControlPanelSession,
} from "./ControlPanel/controlPanelLayout";
import { FilePreviewHost } from "./components/FilePreviewDialog";
import { MessageHandler } from "./MessageHandler";
import { LeikaModal } from "./Modal";
import { defaultWebsocketServer, searchParamKey } from "./SearchParamsUtils";
import { useViewer } from "./ViewerContext";
import { ViewerProvider } from "./ViewerProvider";
import { WebsocketMessageProducer } from "./WebsocketInterface";
import { Toaster } from "./components/ui/toast";
import { TooltipProvider } from "./components/ui/tooltip";
import { useAccentColor } from "./hooks/useAccentColor";
import { useMobileView, usePrefersDarkMode } from "./hooks/useMediaQuery";
import { useThemeColor } from "./hooks/useThemeColor";
import { ViewportWorkspace } from "./viewport/ViewportWorkspace";

export function Root() {
  const searchParams = new URLSearchParams(window.location.search);
  const servers = searchParams.getAll(searchParamKey);
  const initialServer =
    servers[0] ?? defaultWebsocketServer(window.location.href);

  return (
    <ViewerProvider initialServer={initialServer}>
      <ViewerContents>
        <WebsocketMessageProducer />
      </ViewerContents>
    </ViewerProvider>
  );
}

function ViewerContents({ children }: { children: React.ReactNode }) {
  const viewer = useViewer();
  const prefersDarkMode = usePrefersDarkMode();
  const chosenDarkMode = viewer.useSettings((state) => state.darkMode);
  // Settings is the single selection, whether changed by Python or the GUI.
  // Auto always follows the browser, with no server override underneath it.
  const darkMode = chosenDarkMode ?? prefersDarkMode;
  const controlPanel = useControlPanelSession();
  useAccentColor(viewer.useSettings((state) => state.accentColor));
  useThemeColor();

  return (
    // The scheme is resolved above rather than handed to `enableSystem`, so
    // the class on `<html>` stays the single source of truth -- next-themes
    // never gets to override it from its own localStorage.
    <NextThemesProvider
      attribute="class"
      forcedTheme={darkMode ? "dark" : "light"}
      enableSystem={false}
      disableTransitionOnChange
    >
      <TooltipProvider delay={500}>
        <ControlPanelContext.Provider value={controlPanel}>
          {children}
          <MessageHandler />
          <LeikaModal />
          <FilePreviewHost />
          <CommandPalette />
          <AppLayout />
        </ControlPanelContext.Provider>
      </TooltipProvider>
    </NextThemesProvider>
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
