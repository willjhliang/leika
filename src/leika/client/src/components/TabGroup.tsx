import * as React from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiDockContext } from "../ControlPanel/GuiDockContext";
import { GuiTabGroupMessage } from "../WebsocketMessages";
import { IconHtml } from "./common";
import { DockArea } from "../dock/DockArea";
import { DockContext, useDock } from "../dock/DockContext";
import * as layoutOps from "../dock/layoutOps";

export default function TabGroupComponent(message: GuiTabGroupMessage) {
  const dock = React.useContext(DockContext);
  const guiDock = React.useContext(GuiDockContext);
  if (dock !== null && guiDock !== null)
    return <DockableTabGroup {...message} />;
  return <PlainTabGroup {...message} />;
}

function DockableTabGroup({ uuid, props: { _tabs: tabs } }: GuiTabGroupMessage) {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, orderKey, areaId, dock.api]);

  return <DockArea areaId={areaId} minHeight="2.4em" inheritContentPadding />;
}

function PlainTabGroup({ props: { _tabs: tabs } }: GuiTabGroupMessage) {
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
      <TabsList
        className="no-scrollbar w-full min-w-0 justify-start overflow-x-auto"
        data-leika-tabs-list
      >
        {tabs.map((tab) => (
          <TabsTrigger
            data-leika-tab
            className="min-w-fit"
            value={tab.container_id}
            key={tab.container_id}
          >
            {tab.icon_html === null ? null : <IconHtml html={tab.icon_html} />}
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {tabs.map((tab) => (
        <TabsContent value={tab.container_id} key={tab.container_id} keepMounted>
          <GuiContainer containerUuid={tab.container_id} />
        </TabsContent>
      ))}
    </Tabs>
  );
}
