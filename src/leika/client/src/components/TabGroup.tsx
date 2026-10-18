import * as React from "react";

import { cn } from "@/lib/utils";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import type { GuiTab } from "../ControlPanel/GuiState";
import { useViewer } from "../ViewerContext";
import { GuiTabGroupMessage } from "../WebsocketMessages";
import { IconHtml } from "./common";
import { HoverScrollText } from "./HoverScrollText";

/** A GUI tab group: a strip of tabs over their containers, with every tab's
 * contents kept mounted so renderers and half-typed values survive a switch.
 *
 * The strip wraps rather than scrolling: a tab whose words are cut off at an
 * edge, with no scrollbar to say there is more, is a tab nobody can read. It is
 * as tall as the tabs it holds, marked important because the stock list sets a
 * one-line height from the tabs root above it. */
const NO_TABS: GuiTab[] = [];

export default function TabGroupComponent({ uuid }: GuiTabGroupMessage) {
  const { GuiContainer } = useGuiComponent();
  const tabs = useViewer().useGui(
    (state) => state.tabsFromGroupUuid[uuid] ?? NO_TABS,
  );
  // Derived rather than corrected in an effect: when the server drops the
  // selected tab, the first tab takes over on the same render.
  const [selected, setSelected] = React.useState<string | null>(null);
  const activeTab =
    selected !== null && tabs.some((tab) => tab.uuid === selected)
      ? selected
      : (tabs[0]?.uuid ?? null);

  if (activeTab === null) return null;
  return (
    <Tabs value={activeTab} onValueChange={(next) => setSelected(String(next))}>
      <TabsList
        variant="line"
        className="h-auto! w-full min-w-0 flex-wrap justify-start"
        data-leika-tabs-list
      >
        {tabs.map((tab) => (
          <TabsTrigger
            key={tab.uuid}
            value={tab.uuid}
            title={tab.props.label}
            // A lone tab is the group's whole title and takes the whole row;
            // the cap exists so that in a CROWD no one tab hogs the strip.
            className={cn("min-w-fit", tabs.length > 1 && "max-w-56")}
            data-leika-tab
          >
            {tab.props._icon_html !== null && (
              <IconHtml html={tab.props._icon_html} />
            )}
            {/* A tab is not worth widening the strip for: past `max-w-56` the
                label gives way. `TabsTrigger` is a flex box, so the ellipsis
                has to be asked for on a box inside it. */}
            <HoverScrollText>{tab.props.label}</HoverScrollText>
          </TabsTrigger>
        ))}
      </TabsList>
      {tabs.map((tab) => (
        <TabsContent value={tab.uuid} key={tab.uuid} keepMounted>
          <GuiContainer containerUuid={tab.uuid} />
        </TabsContent>
      ))}
    </Tabs>
  );
}
