import GeneratedGuiContainer from "./Generated";
import { ViewerContext } from "../ViewerContext";

import { Collapsible, CollapsibleContent } from "../components/ui/collapsible";
import { Status, StatusIndicator, StatusLabel } from "../components/ui/status";
import React from "react";
import BottomPanel from "./BottomPanel";
import { CONTROL_WIDTH_CSS } from "./controlWidth";
import { ThemeConfigurationMessage } from "../WebsocketMessages";
import { useMobileView } from "../hooks/useMediaQuery";
import SidebarPanel from "./SidebarPanel";
import { useShowGenerated } from "./useShowGenerated";

// Must match constant in Python.
const ROOT_CONTAINER_ID = "root";

const MemoizedGeneratedGuiContainer = React.memo(GeneratedGuiContainer);

/** The control panel's body: the generated GUI. Shared by every panel chrome
 * (bottom sheet, sidebar, and the dock-library floating panel). */
export function ControlPanelContents() {
  const showGenerated = useShowGenerated();
  return (
    /*For intrinsic-size transitions, this `keepMounted` is necessary to prevent
    some intermittent problems with the initial GUI height being set to 0 when
    we're under high CPU load.*/
    <Collapsible open={showGenerated}>
      <CollapsibleContent keepMounted>
        <MemoizedGeneratedGuiContainer containerUuid={ROOT_CONTAINER_ID} />
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
    /* Mobile layout. */
    return (
      <BottomPanel>
        <BottomPanel.Handle>
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
          <PanelHeader />
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
 * wants between the two.
 *
 * The title and status used to share one slot, with the title displacing the
 * status text whenever a server set one, so neither was reliably visible. */
export function PanelHeader({ actions }: { actions?: React.ReactNode }) {
  const { useGui } = React.useContext(ViewerContext)!;
  const websocketState = useGui((state) => state.websocketState);
  const label = useGui((state) => state.label);
  const { status, text } = CONNECTION_STATUS[websocketState];

  return (
    <div className="flex min-w-0 flex-1 items-center gap-2">
      {/* The title is whatever the server passed as its panel label, so it is
          empty until one is set. Typed like a GUI row's field label, so the
          panel reads with one voice from its header down. */}
      <span className="min-w-0 flex-1 truncate text-sm font-normal text-muted-foreground leading-tight">
        {label}
      </span>
      {actions}
      {/* The badge keeps the Badge base's `shrink-0`, so a long title
          truncates rather than squeezing the status. */}
      <Status status={status}>
        <StatusIndicator />
        <StatusLabel>{text}</StatusLabel>
      </Status>
    </div>
  );
}
