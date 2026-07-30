import GeneratedGuiContainer from "./Generated";
import { ViewerContext } from "../ViewerContext";
import { guiLabelClassName } from "../components/guiLabelStyles";
import { cn } from "../lib/utils";

import { Collapsible, CollapsibleContent } from "../components/ui/collapsible";
import { Status, StatusIndicator, StatusLabel } from "../components/ui/status";
import React from "react";
import BottomPanel from "./BottomPanel";
import { CONTROL_WIDTH_CSS } from "./controlWidth";
import { ThemeConfigurationMessage } from "../WebsocketMessages";
import { useMobileView } from "../hooks/useMediaQuery";
import { SettingsButton } from "./SettingsPane";
import { useControlsShown } from "./SettingsPanelController";
import SidebarPanel from "./SidebarPanel";
import { useShowGenerated } from "./useShowGenerated";

// Must match constant in Python.
const ROOT_CONTAINER_ID = "root";

const MemoizedGeneratedGuiContainer = React.memo(GeneratedGuiContainer);

/** The control panel's body: the generated GUI. Shared by every panel chrome
 * (bottom sheet, sidebar, and the dock-library floating panel). */
export function ControlPanelContents() {
  const hasGenerated = useShowGenerated();
  // The handle's flag. The controls stay MOUNTED when hidden rather than being
  // dropped, so half-typed values and the heights the intrinsic-size
  // transitions measure both survive being folded away.
  //
  // The gear's flag is not in here: the browser's own settings open in a
  // popout off the header, so the body holds the app's controls and nothing
  // else.
  const controlsShown = useControlsShown();
  return (
    /*For intrinsic-size transitions, this `keepMounted` is necessary to prevent
    some intermittent problems with the initial GUI height being set to 0 when
    we're under high CPU load.*/
    <Collapsible open={hasGenerated && controlsShown}>
      <CollapsibleContent keepMounted>
        <div hidden={!controlsShown} data-leika-generated-gui>
          <MemoizedGeneratedGuiContainer containerUuid={ROOT_CONTAINER_ID} />
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export default function ControlPanel(props: {
  control_layout: ThemeConfigurationMessage["control_layout"];
}) {
  const mobileView = useMobileView();
  const panelContents = <ControlPanelContents />;

  // NOTE: the "floating" layout never reaches this component -- App renders it
  // on the docking surface (see ControlPanelDock.tsx). This component covers
  // the mobile bottom sheet and the sidebar layouts.
  if (mobileView) {
    /* Mobile layout. The whole handle is the collapse button, so the gear
       cannot sit inside the header the way it does elsewhere; it goes beside
       it instead. */
    return (
      <BottomPanel>
        <BottomPanel.Handle actions={<SettingsButton />}>
          <PanelHeader />
        </BottomPanel.Handle>
        <BottomPanel.Contents>{panelContents}</BottomPanel.Contents>
      </BottomPanel>
    );
  } else {
    /* Sidebar view. */
    return (
      <SidebarPanel
        width={CONTROL_WIDTH_CSS}
        collapsible={props.control_layout === "collapsible"}
      >
        <SidebarPanel.Handle>
          <PanelHeader actions={<SettingsButton />} />
        </SidebarPanel.Handle>
        <SidebarPanel.Contents>{panelContents}</SidebarPanel.Contents>
      </SidebarPanel>
    );
  }
}

/** Websocket states, as the Status component's vocabulary. Leika has nothing
 * that maps to "maintenance", which the server would have to be up to report.
 * The wording is load-bearing: the browser tests wait for "Connecting..." to
 * leave the page before they touch anything. */
const CONNECTION_STATUS = {
  connected: { status: "online", text: "Connected" },
  reconnecting: { status: "degraded", text: "Connecting..." },
  inactive: { status: "offline", text: "Inactive" },
} as const;

/** The panel header's contents: the visualization's title on the left, the
 * websocket connection status on the right, and whatever the chrome around it
 * wants between the two. */
export function PanelHeader({ actions }: { actions?: React.ReactNode }) {
  const { useGui } = React.useContext(ViewerContext)!;
  const websocketState = useGui((state) => state.websocketState);
  const label = useGui((state) => state.label);
  const { status, text } = CONNECTION_STATUS[websocketState];

  return (
    // Collapsed, the floating panel fades down to the one thing worth leaving
    // on the canvas: the connection badge. The title and the gear go with the
    // card (`data-dock-peek-fade`); the badge stays and is what the pointer
    // comes back to (`data-dock-peek`). Inert in every other chrome -- the
    // sidebar and the bottom sheet have no such state to be in.
    <div
      className="flex min-w-0 flex-1 items-center gap-2"
      // What the settings popout aligns to: the gear is a 20px circle in the
      // middle of this row, and a popout hung off it would sit wherever the
      // title's length left it. See SettingsButton.
      data-leika-panel-header
    >
      {/* The title is whatever the server passed as its panel label, so it is
          empty until one is set. Typed like a GUI row's field label, so the
          panel reads with one voice from its header down. */}
      <span
        className={cn("min-w-0 flex-1 truncate text-sm", guiLabelClassName)}
        data-dock-peek-fade
      >
        {label}
      </span>
      {actions !== undefined && (
        <span className="inline-flex" data-dock-peek-fade>
          {actions}
        </span>
      )}
      {/* The badge keeps the Badge base's `shrink-0`, so a long title
          truncates rather than squeezing the status. */}
      <Status status={status} data-dock-peek>
        <StatusIndicator />
        <StatusLabel>{text}</StatusLabel>
      </Status>
    </div>
  );
}
