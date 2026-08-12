import React from "react";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader } from "../components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "../components/ui/collapsible";
import { ScrollArea } from "../components/ui/scroll-area";
import { Separator } from "../components/ui/separator";
import { cn } from "../lib/utils";
import { useViewer } from "../ViewerContext";
import { CONTROL_MAX_WIDTH_CLASS } from "./controlWidth";

const BottomPanelContext = React.createContext<null | {
  expanded: boolean;
}>(null);

/** A bottom panel is used to display the controls on mobile devices. */
export default function BottomPanel({
  children,
}: {
  children: string | React.ReactNode;
}) {
  const viewer = useViewer();
  const expanded = viewer.useSettings((state) => state.mobileControlsExpanded);
  const { setMobileControlsExpanded } = viewer.settingsActions;
  return (
    <BottomPanelContext.Provider value={{ expanded }}>
      <Card
        className={cn(
          "fixed right-0 bottom-0 z-10 w-full gap-0 shadow-md",
          CONTROL_MAX_WIDTH_CLASS,
          expanded && "h-[60vh]",
        )}
      >
        <Collapsible
          open={expanded}
          onOpenChange={setMobileControlsExpanded}
          className="contents"
        >
          {children}
        </Collapsible>
      </Card>
    </BottomPanelContext.Provider>
  );
}
BottomPanel.Handle = function BottomPanelHandle({
  children,
  actions,
}: {
  children: string | React.ReactNode;
  /** Controls of their own, placed beside the trigger rather than inside it:
   * the whole handle is one button here, and a button cannot hold another. */
  actions?: React.ReactNode;
}) {
  const panelContext = React.useContext(BottomPanelContext)!;
  return (
    <CardHeader className="flex h-12 shrink-0 flex-row items-center gap-0 py-0">
      <CollapsibleTrigger
        render={
          <Button
            type="button"
            variant="ghost"
            className="min-w-0 flex-1 justify-start px-0"
            aria-label={
              panelContext.expanded ? "Collapse controls" : "Expand controls"
            }
            data-leika-bottom-panel-handle
          />
        }
      >
        {children}
      </CollapsibleTrigger>
      {actions}
    </CardHeader>
  );
};

/** Contents of a panel. */
BottomPanel.Contents = function BottomPanelContents({
  children,
}: {
  children: string | React.ReactNode;
}) {
  return (
    <CollapsibleContent className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <Separator />
      {/* The same top-bleed the dock panels carry (see TabGroupFrame): room
          for first-row ink above its box, at no change in layout. */}
      <ScrollArea className="-mt-1 h-0 min-h-0 flex-1 [&_[data-slot=scroll-area-viewport]]:pt-1">
        <CardContent>{children}</CardContent>
      </ScrollArea>
    </CollapsibleContent>
  );
};
