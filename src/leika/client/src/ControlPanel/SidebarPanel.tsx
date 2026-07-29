// @refresh reset

import React from "react";
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { Button } from "../components/ui/button";
import { Separator } from "../components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "../components/ui/tooltip";

const SidebarPanelContext = React.createContext<null | {
  collapsible: boolean;
  toggleCollapsed: () => void;
}>(null);

/** A fixed or collapsible side panel for displaying controls. */
export default function SidebarPanel({
  children,
  collapsible,
  width,
}: {
  children: React.ReactNode;
  collapsible: boolean;
  width: string;
}) {
  const [collapsed, setCollapsed] = React.useState(false);
  const toggleCollapsed = React.useCallback(
    () => setCollapsed((current) => !current),
    [],
  );
  const contextValue = React.useMemo(
    () => ({ collapsible, toggleCollapsed }),
    [collapsible, toggleCollapsed],
  );

  return (
    <SidebarPanelContext.Provider value={contextValue}>
      {collapsed ? (
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="outline"
                size="icon"
                className="absolute top-2 right-2 z-20"
                aria-label="Show sidebar"
                onClick={(event) => {
                  event.stopPropagation();
                  toggleCollapsed();
                }}
              />
            }
          >
            <ChevronLeftIcon />
          </TooltipTrigger>
          <TooltipContent>Show sidebar</TooltipContent>
        </Tooltip>
      ) : (
        <div
          data-slot="sidebar"
          // The sidebar is the one panel chrome that is not a card, so it
          // says so for whatever inside it has to paint its own surface.
          className="flex h-full w-(--sidebar-width) flex-col bg-sidebar text-sidebar-foreground [--leika-panel-surface:var(--sidebar)]"
          style={{ "--sidebar-width": width } as React.CSSProperties}
        >
          {children}
        </div>
      )}
    </SidebarPanelContext.Provider>
  );
}

/** Header row: connection status plus the panel's action buttons. */
SidebarPanel.Handle = function SidebarPanelHandle({
  children,
}: {
  children: React.ReactNode;
}) {
  const { toggleCollapsed, collapsible } =
    React.useContext(SidebarPanelContext)!;

  return (
    <>
      <div
        data-slot="sidebar-header"
        className="flex flex-row items-center gap-2 p-2"
      >
        {children}
        {collapsible ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Collapse sidebar"
                  onClick={(event) => {
                    event.stopPropagation();
                    toggleCollapsed();
                  }}
                />
              }
            >
              <ChevronRightIcon />
            </TooltipTrigger>
            <TooltipContent>Collapse sidebar</TooltipContent>
          </Tooltip>
        ) : null}
      </div>
      <Separator className="mx-2 w-auto bg-sidebar-border" />
    </>
  );
};

/** Scrollable body of the panel. */
SidebarPanel.Contents = function SidebarPanelContents({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div
      data-slot="sidebar-content"
      className="no-scrollbar flex min-h-0 flex-1 flex-col overflow-auto"
    >
      <div
        data-slot="sidebar-group"
        className="relative flex w-full min-w-0 flex-col p-2"
      >
        <div data-slot="sidebar-group-content" className="w-full text-sm">
          {children}
        </div>
      </div>
    </div>
  );
};
