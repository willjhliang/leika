import * as React from "react";

import { Tabs, TabsContent } from "@/components/ui/tabs";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiDockContext } from "../ControlPanel/GuiDockContext";
import { GuiTabGroupMessage } from "../WebsocketMessages";
import { IconHtml } from "./common";
import { TabStrip } from "./TabStrip";
import { DockArea } from "../dock/DockArea";
import { DockContext, useDock } from "../dock/DockContext";
import * as layoutOps from "../dock/layoutOps";

/**
 * A tab group, with or without the dragging.
 *
 * One kind of tab either way: both forms draw the same `TabStrip` and the same
 * bodies under it, and what a dock adds is that its tabs can be torn out into
 * windows of their own, dropped into another panel, or reordered. It used to
 * add a different-looking strip as well -- a filled pill strip that scrolled
 * its overflow away silently, against an underlined one that wrapped -- and
 * which an author got was decided by the panel's chrome setting, which has no
 * visible connection to a tab group at all.
 *
 * Dragging cannot simply be switched on here, because a tab that can be torn
 * out has to BE a dock panel: the dock is what holds it once it is out, and
 * what draws it wherever it lands. So the draggable form hands its tabs over
 * to the dock as panels and lets the dock place them, and the fixed form keeps
 * them and draws them itself. The fork is which of those two owns the bodies;
 * it is not a fork in what a tab group looks like.
 */
export default function TabGroupComponent(message: GuiTabGroupMessage) {
  const dock = React.useContext(DockContext);
  const guiDock = React.useContext(GuiDockContext);
  // Both, or neither: the panel registry and the dock that renders it are two
  // halves of the same surface.
  if (dock !== null && guiDock !== null)
    return <DraggableTabGroup {...message} />;
  return <FixedTabGroup {...message} />;
}

/** Tabs the viewer can pull apart: each becomes a panel of the dock's, and the
 * group becomes an area for the dock to place them in. */
function DraggableTabGroup({
  uuid,
  props: { _tabs: tabs },
}: GuiTabGroupMessage) {
  const dock = useDock();
  const guiDock = React.useContext(GuiDockContext)!;
  const areaId = `gui-tabs-${uuid}`;

  React.useEffect(() => guiDock.registerTabGroup(uuid), [uuid, guiDock]);
  const tabContainerIds = tabs.map((tab) => tab.container_id);
  const ready = tabContainerIds.every((id) => dock.panels[id] !== undefined);
  const orderKey = tabContainerIds.join("\n");
  React.useEffect(() => {
    if (!ready) return;
    tabContainerIds.forEach((id, index) =>
      dock.api.addPanelToArea(areaId, id, index),
    );
    dock.api.apply((layout) =>
      layoutOps.setAreaTabOrder(layout, areaId, tabContainerIds),
    );
  }, [ready, orderKey, areaId, dock.api]);

  return <DockArea areaId={areaId} minHeight="2.4em" inheritContentPadding />;
}

/** Tabs that stay where they are, drawn here rather than by a dock. */
function FixedTabGroup({ props: { _tabs: tabs } }: GuiTabGroupMessage) {
  const { GuiContainer } = React.useContext(GuiComponentContext)!;
  // Derived rather than corrected in an effect: when the server drops the
  // selected tab, the first tab takes over on the same render.
  const [selected, setSelected] = React.useState<string | null>(null);
  const activeTab =
    selected !== null && tabs.some((tab) => tab.container_id === selected)
      ? selected
      : (tabs[0]?.container_id ?? null);

  if (activeTab === null) return null;
  return (
    <Tabs value={activeTab} onValueChange={(next) => setSelected(String(next))}>
      <TabStrip
        tabs={tabs.map((tab) => ({
          id: tab.container_id,
          label: tab.label,
          icon:
            tab.icon_html === null ? undefined : (
              <IconHtml html={tab.icon_html} />
            ),
        }))}
      />
      {tabs.map((tab) => (
        <TabsContent
          value={tab.container_id}
          key={tab.container_id}
          keepMounted
        >
          <GuiContainer containerUuid={tab.container_id} />
        </TabsContent>
      ))}
    </Tabs>
  );
}
