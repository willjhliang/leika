// @refresh reset
import "./index.css";

import React from "react";
import { ThemeProvider as NextThemesProvider } from "next-themes";

import { useClientSettings } from "./ClientSettings";
import { CommandPalette } from "./CommandPalette";
import ControlPanel from "./ControlPanel/ControlPanel";
import {
  ControlDockState,
  ControlPanelDockSurface,
} from "./ControlPanel/ControlPanelDock";
import { useGuiState } from "./ControlPanel/GuiState";
import { FilePreviewHost } from "./components/FilePreviewDialog";
import { MessageHandler } from "./MessageHandler";
import { FileDownloadAssembler } from "./fileDownloadAssembler";
import { LeikaModal } from "./Modal";
import { defaultWebsocketServer, searchParamKey } from "./SearchParamsUtils";
import {
  ViewerContext,
  ViewerContextContents,
  ViewerMutable,
  useViewer,
  warnDisconnectedSend,
} from "./ViewerContext";
import { WebsocketMessageProducer } from "./WebsocketInterface";
import { ThemeConfigurationMessage } from "./WebsocketMessages";
import { Toaster } from "./components/ui/toast";
import { TooltipProvider } from "./components/ui/tooltip";
import { useAccentColor } from "./hooks/useAccentColor";
import { useMobileView, usePrefersDarkMode } from "./hooks/useMediaQuery";
import { useThemeColor } from "./hooks/useThemeColor";
import { useViewportState } from "./viewport/ViewportState";
import { ViewportWorkspace } from "./viewport/ViewportWorkspace";

export function Root() {
  const searchParams = new URLSearchParams(window.location.search);
  const servers = searchParams.getAll(searchParamKey);
  const initialServer =
    servers[0] ?? defaultWebsocketServer(window.location.href);

  const mutable = React.useRef<ViewerMutable>({
    sendMessage: warnDisconnectedSend,
    messageQueue: [],
    notifyMessageQueue: () => undefined,
    downloads: new FileDownloadAssembler(),
  });
  const guiState = useGuiState(initialServer);
  const viewportState = useViewportState();
  const settingsState = useClientSettings();
  // Memoized: a rebuilt context value would re-render every consumer in the
  // app whenever `Root` re-renders.
  const viewer: ViewerContextContents = React.useMemo(
    () => ({
      useGui: guiState.store,
      useGuiConfig: guiState.configStore,
      guiActions: guiState.actions,
      useViewport: viewportState.store,
      viewportActions: viewportState.actions,
      useSettings: settingsState.store,
      settingsActions: settingsState.actions,
      mutable,
    }),
    [guiState, viewportState, settingsState],
  );

  return (
    <ViewerContext.Provider value={viewer}>
      <ViewerContents>
        <WebsocketMessageProducer />
      </ViewerContents>
    </ViewerContext.Provider>
  );
}

function ViewerContents({ children }: { children: React.ReactNode }) {
  const viewer = useViewer();
  const configuredDarkMode = viewer.useGui((state) => state.theme.dark_mode);
  const prefersDarkMode = usePrefersDarkMode();
  const chosenDarkMode = viewer.useSettings((state) => state.darkMode);
  // "auto" is the default the server sends, and what the store holds before it
  // connects, so the OS preference decides unless an app opts out of it. Two
  // viewers of the same app can legitimately land on different schemes.
  //
  // A viewer who has worked the settings switch outranks both: the app's
  // choice is a default, and the reader's is a decision.
  const darkMode =
    chosenDarkMode ??
    (configuredDarkMode === "auto" ? prefersDarkMode : configuredDarkMode);
  const controlLayout = viewer.useGui((state) => state.theme.control_layout);
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
        {children}
        <MessageHandler />
        <LeikaModal />
        <FilePreviewHost />
        <CommandPalette />
        <AppLayout controlLayout={controlLayout} />
      </TooltipProvider>
    </NextThemesProvider>
  );
}

function AppLayout({
  controlLayout,
}: {
  controlLayout: ThemeConfigurationMessage["control_layout"];
}) {
  const mobileView = useMobileView();
  const [controlDock, setControlDock] = React.useState<ControlDockState>({
    side: null,
    widthPx: 320,
    expanded: true,
  });

  React.useEffect(() => {
    // The dock surface unmounts on the way into the mobile view, and a stale
    // `side: "left"` would keep the toasts inset off a panel that is no longer
    // there.
    if (mobileView) {
      setControlDock((previous) =>
        previous.side === null ? previous : { ...previous, side: null },
      );
    }
  }, [mobileView]);

  return (
    <div className="relative flex size-full flex-col">
      <div className="relative flex w-full flex-1 overflow-hidden">
        <NotificationsPanel
          dockedLeftInsetPx={
            controlDock.side === "left" && controlDock.expanded
              ? controlDock.widthPx
              : null
          }
        />
        <div className="relative h-full flex-1 overflow-hidden bg-background">
          {/* Desktop always gets the dock; `controlLayout` is where the panel
              STARTS, which the dock surface applies. The phone's bottom sheet
              is the one chrome the dock cannot absorb. */}
          {mobileView ? (
            <ViewportWorkspace />
          ) : (
            <ControlPanelDockSurface
              controlLayout={controlLayout}
              onDockStateChange={setControlDock}
            >
              <ViewportWorkspace />
            </ControlPanelDockSurface>
          )}
        </div>
        {mobileView && <ControlPanel />}
      </div>
    </div>
  );
}

function NotificationsPanel({
  dockedLeftInsetPx,
}: {
  dockedLeftInsetPx: number | null;
}) {
  // The toast viewport defaults to the bottom-right corner. Leika keeps
  // notifications on the LEFT, pushed clear of a left-docked control panel so
  // they never stack underneath it. Placement is inline rather than utility
  // classes because the inset is a live pixel measurement from the dock; the
  // width shrinks with it so a wide docked panel can't push toasts off-screen.
  const insetPx = dockedLeftInsetPx ?? 0;
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
