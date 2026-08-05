import GeneratedGuiContainer from "./Generated";
import { ViewerContext } from "../ViewerContext";
import { guiLabelClassName } from "../components/guiLabelStyles";
import { cn } from "../lib/utils";

import { Collapsible, CollapsibleContent } from "../components/ui/collapsible";
import React from "react";
import { ConnectionBadge } from "./ConnectionPane";
import BottomPanel from "./BottomPanel";
import { SettingsButton } from "./SettingsPane";
import { useControlsShown } from "./SettingsPanelController";
import { useShowGenerated } from "./useShowGenerated";

// Must match constant in Python.
const ROOT_CONTAINER_ID = "root";

const MemoizedGeneratedGuiContainer = React.memo(GeneratedGuiContainer);

/** The control panel's body: the generated GUI. Shared by both panel chromes
 * (the phone's bottom sheet and the desktop dock panel). */
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
    // Intrinsic-size transitions need a mounted body to measure.
    <Collapsible open={hasGenerated && controlsShown}>
      <CollapsibleContent keepMounted>
        <div hidden={!controlsShown} data-leika-generated-gui>
          <MemoizedGeneratedGuiContainer containerUuid={ROOT_CONTAINER_ID} />
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

/** The phone's control panel: a bottom sheet. Desktop always uses the dock
 * (ControlPanelDockSurface); App renders this only in the mobile view.
 *
 * The whole handle is the collapse button, so neither the gear nor the
 * connection badge -- both buttons of their own -- can sit inside the header
 * the way they do elsewhere; they go beside it, in the order the header would
 * have put them. */
export default function ControlPanel() {
  return (
    <BottomPanel>
      <BottomPanel.Handle
        actions={
          <span className="flex items-center gap-2">
            <ConnectionBadge />
            <SettingsButton />
          </span>
        }
      >
        <PanelHeader badge={null} />
      </BottomPanel.Handle>
      <BottomPanel.Contents>
        <ControlPanelContents />
      </BottomPanel.Contents>
    </BottomPanel>
  );
}

/** The panel header's contents: the visualization's title on the left, the
 * websocket connection status on the right, and whatever the chrome around it
 * wants between the two. */
export function PanelHeader({
  actions,
  badge = <ConnectionBadge />,
}: {
  actions?: React.ReactNode;
  /** The connection badge, or `null` where the header is itself inside a
   * button and cannot hold one. */
  badge?: React.ReactNode;
}) {
  const { useGui } = React.useContext(ViewerContext)!;
  const label = useGui((state) => state.label);

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
      {/* The badge is a button onto what the connection is doing: it is the
          one thing left on the canvas when the panel folds away, so it is
          where a reader already looks when something feels wrong. */}
      {badge}
    </div>
  );
}
