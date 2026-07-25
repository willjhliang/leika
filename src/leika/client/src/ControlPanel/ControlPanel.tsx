import GeneratedGuiContainer from "./Generated";
import { ViewerContext } from "../ViewerContext";

import ServerControls from "./ServerControls";
import {
  ArrowLeftIcon,
  CloudCheckIcon,
  ListFilterIcon,
  PauseIcon,
  Settings2Icon,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Collapsible, CollapsibleContent } from "../components/ui/collapsible";
import { Spinner } from "../components/ui/spinner";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "../components/ui/tooltip";
import { commandPalette } from "../CommandPaletteController";
import { isMac } from "../utils/platform";
import React from "react";
import BottomPanel from "./BottomPanel";
import { controlWidthEm } from "./controlWidth";
import { ThemeConfigurationMessage } from "../WebsocketMessages";
import { useMobileView } from "../hooks/useMediaQuery";
import SidebarPanel from "./SidebarPanel";

// Must match constant in Python.
const ROOT_CONTAINER_ID = "root";

const MemoizedGeneratedGuiContainer = React.memo(GeneratedGuiContainer);

/** True when the root container has any generated GUI to show. */
function useShowGenerated(): boolean {
  const viewer = React.useContext(ViewerContext)!;
  return viewer.useGui(
    (state) =>
      Object.keys(state.guiUuidSetFromContainerUuid["root"] ?? {}).length > 0,
  );
}

/** The control panel's body: server controls / generated GUI, toggled by the
 * settings button in the handle. Shared by every panel chrome (bottom sheet,
 * sidebar, and the dock-library floating panel). */
export function ControlPanelContents({
  showSettings,
}: {
  showSettings: boolean;
}) {
  const showGenerated = useShowGenerated();
  return (
    <>
      <Collapsible open={!showGenerated || showSettings}>
        <CollapsibleContent>
          <ServerControls />
        </CollapsibleContent>
      </Collapsible>
      {/*For intrinsic-size transitions, this `keepMounted` is necessary to prevent some
      intermittent problems with the initial GUI height being set to 0 when
      we're under high CPU load.*/}
      <Collapsible open={showGenerated && !showSettings}>
        <CollapsibleContent keepMounted>
          <MemoizedGeneratedGuiContainer containerUuid={ROOT_CONTAINER_ID} />
        </CollapsibleContent>
      </Collapsible>
    </>
  );
}

/** Handle button toggling between the generated GUI and the connection settings view. Hidden until there is generated GUI to return to. */
export function SettingsToggleIcon({
  showSettings,
  onToggle,
}: {
  showSettings: boolean;
  onToggle: () => void;
}) {
  const showGenerated = useShowGenerated();
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            className={showGenerated ? undefined : "hidden"}
            aria-label={showSettings ? "Return to GUI" : "Connection settings"}
            onClick={(event) => {
              event.stopPropagation();
              onToggle();
            }}
          />
        }
      >
        {showSettings ? <ArrowLeftIcon /> : <Settings2Icon />}
      </TooltipTrigger>
      <TooltipContent>
        {showSettings ? "Return to GUI" : "Connection settings"}
      </TooltipContent>
    </Tooltip>
  );
}

export default function ControlPanel(props: {
  control_layout: ThemeConfigurationMessage["control_layout"];
}) {
  const mobileView = useMobileView();
  const viewer = React.useContext(ViewerContext)!;
  const [showSettings, setShowSettings] = React.useState(false);
  const toggle = React.useCallback(
    () => setShowSettings((current) => !current),
    [],
  );

  const controlWidthString = viewer.useGui(
    (state) => state.theme.control_width,
  );
  const controlWidth = controlWidthEm(controlWidthString);

  const generatedServerToggleButton = (
    <SettingsToggleIcon showSettings={showSettings} onToggle={toggle} />
  );

  const panelContents = <ControlPanelContents showSettings={showSettings} />;

  // NOTE: the "floating" layout never reaches this component -- App renders it
  // on the docking surface (see ControlPanelDock.tsx). This component covers
  // the mobile bottom sheet and the sidebar layouts.
  if (mobileView) {
    /* Mobile layout. */
    return (
      <BottomPanel>
        <BottomPanel.Handle
          actions={
            <BottomPanel.HideWhenCollapsed>
              <CommandsButton />
              {generatedServerToggleButton}
            </BottomPanel.HideWhenCollapsed>
          }
        >
          <ConnectionStatus />
        </BottomPanel.Handle>
        <BottomPanel.Contents>{panelContents}</BottomPanel.Contents>
      </BottomPanel>
    );
  } else {
    /* Sidebar view. */
    return (
      <SidebarPanel
        width={controlWidth}
        collapsible={props.control_layout === "collapsible"}
      >
        <SidebarPanel.Handle>
          <ConnectionStatus />
          <CommandsButton />
          {generatedServerToggleButton}
        </SidebarPanel.Handle>
        <SidebarPanel.Contents>{panelContents}</SidebarPanel.Contents>
      </SidebarPanel>
    );
  }
}

/* Icon and label telling us the current status of the websocket connection. */
export function ConnectionStatus() {
  const { useGui } = React.useContext(ViewerContext)!;
  const websocketState = useGui((state) => state.websocketState);
  const label = useGui((state) => state.label);

  return (
    <div className="flex min-w-0 flex-1 items-center gap-2">
      {websocketState === "connected" ? (
        <CloudCheckIcon className="size-4 shrink-0 text-muted-foreground" />
      ) : websocketState === "reconnecting" ? (
        <Spinner className="size-4 shrink-0 text-destructive" />
      ) : (
        <PauseIcon className="size-4 shrink-0 text-destructive" />
      )}
      <span className="min-w-0 flex-1 truncate">
        {label !== ""
          ? label
          : websocketState === "connected"
            ? "Connected"
            : websocketState === "reconnecting"
              ? "Connecting..."
              : "Inactive"}
      </span>
    </div>
  );
}

export function CommandsButton() {
  const viewer = React.useContext(ViewerContext)!;
  const hasCommands = viewer.useGui(
    (state) => Object.keys(state.commands).length > 0,
  );

  if (!hasCommands) return null;

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Commands"
            onClick={(event) => {
              event.stopPropagation();
              commandPalette.open();
            }}
          />
        }
      >
        <ListFilterIcon />
      </TooltipTrigger>
      <TooltipContent>{`Commands (${isMac ? "Cmd" : "Ctrl"}+K)`}</TooltipContent>
    </Tooltip>
  );
}
