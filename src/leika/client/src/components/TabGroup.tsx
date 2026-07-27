import * as React from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiDockContext } from "../ControlPanel/GuiDockContext";
import { GuiTabGroupMessage } from "../WebsocketMessages";
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

function DockableTabGroup({
  uuid,
  props: { _tab_container_ids: tabContainerIds },
}: GuiTabGroupMessage) {
  const dock = useDock();
  const guiDock = React.useContext(GuiDockContext)!;
  const areaId = `gui-tabs-${uuid}`;

  React.useEffect(() => guiDock.registerTabGroup(uuid), [uuid, guiDock]);
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

function PlainTabGroup({
  props: {
    _tab_labels: tabLabels,
    _tab_icons_html: tabIconsHtml,
    _tab_container_ids: tabContainerIds,
  },
}: GuiTabGroupMessage) {
  const { GuiContainer } = React.useContext(GuiComponentContext)!;
  const [activeTab, setActiveTab] = React.useState<string | null>(
    tabContainerIds[0] ?? null,
  );

  React.useEffect(() => {
    if (activeTab === null || !tabContainerIds.includes(activeTab)) {
      setActiveTab(tabContainerIds[0] ?? null);
    }
  }, [tabContainerIds, activeTab]);

  if (activeTab === null) return null;
  return (
    <Tabs
      value={activeTab}
      onValueChange={(next) => setActiveTab(String(next))}
    >
      <TabsList
        className="no-scrollbar w-full min-w-0 justify-start overflow-x-auto"
        data-leika-tabs-list
      >
        {tabLabels.map((label, index) => (
          <TabsTrigger
            data-leika-tab
            className="min-w-fit"
            value={tabContainerIds[index]}
            key={tabContainerIds[index]}
          >
            {tabIconsHtml[index] === null ? null : (
              <span
                data-icon="inline-start"
                className="size-3.5 [&_svg]:size-full"
                dangerouslySetInnerHTML={{ __html: tabIconsHtml[index]! }}
              />
            )}
            {label}
          </TabsTrigger>
        ))}
      </TabsList>
      {tabContainerIds.map((containerUuid) => (
        <TabsContent value={containerUuid} key={containerUuid} keepMounted>
          <GuiContainer containerUuid={containerUuid} />
        </TabsContent>
      ))}
    </Tabs>
  );
}
