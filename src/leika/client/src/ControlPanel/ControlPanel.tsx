import GeneratedGuiContainer from "./Generated";
import { useViewer } from "../ViewerContext";
import { HoverScrollText } from "../components/HoverScrollText";
import { guiLabelClassName } from "../components/guiLabelStyles";
import { cn } from "../lib/utils";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import React from "react";
import { ConnectionBadge } from "./ConnectionPane";
import BottomPanel from "./BottomPanel";
import { SettingsButton } from "./SettingsPane";
import { ROOT_GUI_CONTAINER_ID } from "./guiConstants";

const MemoizedGeneratedGuiContainer = React.memo(GeneratedGuiContainer);

interface PageSelectorItem {
  value: string;
  label: string;
}

function samePageSelectorItems(
  left: readonly PageSelectorItem[],
  right: readonly PageSelectorItem[],
): boolean {
  return (
    left.length === right.length &&
    left.every(
      (item, index) =>
        item.value === right[index].value && item.label === right[index].label,
    )
  );
}

/** The active page's name: a plain label when it is the only page, or the same
 * popup and keyboard behavior as every other Leika select when there is a
 * choice, while leaving the panel's title-bar styling intact. */
export function PageSelector() {
  const viewer = useViewer();
  const activePageId = viewer.useViewport((state) => state.activePageId);
  const items = viewer.useViewport(
    (state): PageSelectorItem[] =>
      state.pageOrder.flatMap((pageId) => {
        const page = state.pages[pageId];
        return page === undefined
          ? []
          : [{ value: page.pageId, label: page.name }];
      }),
    samePageSelectorItems,
  );
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    if (items.length <= 1) setOpen(false);
  }, [items.length]);

  if (items.length === 0) return null;
  if (items.length === 1) {
    return (
      <HoverScrollText
        className={cn(
          "inline-flex h-6 min-w-0 max-w-full shrink items-center",
          guiLabelClassName,
        )}
        data-leika-page-title
      >
        {items[0].label}
      </HoverScrollText>
    );
  }
  const activeName =
    items.find((item) => item.value === activePageId)?.label ?? "";

  return (
    // The surrounding panel header starts its drag/collapse gesture on
    // pointerdown. The selector is the one interactive part of that title bar,
    // so its press belongs only to the select; the sibling space remains the
    // drag handle.
    <span
      className="inline-flex min-w-0 max-w-full shrink"
      onPointerDown={(event) => event.stopPropagation()}
    >
      <Select
        items={items}
        value={activePageId}
        open={open}
        onOpenChange={setOpen}
        onValueChange={(next) => {
          if (next !== null && next !== activePageId) {
            viewer.viewportActions.setActivePage(next);
          }
        }}
      >
        <SelectTrigger
          aria-label={activeName === "" ? "Select page" : `Page: ${activeName}`}
          className={cn(
            "h-6 min-w-0 max-w-full rounded-none border-0 bg-transparent p-0 shadow-none hover:bg-transparent focus-visible:border-transparent focus-visible:ring-1 focus-visible:ring-ring data-[size=default]:h-6 dark:bg-transparent dark:hover:bg-transparent [&_svg]:text-current",
            guiLabelClassName,
          )}
          data-leika-page-selector
        >
          <SelectValue className="block! min-w-0">
            <HoverScrollText>{activeName}</HoverScrollText>
          </SelectValue>
        </SelectTrigger>
        {/* A page switch should not change the menu's geometry. Item-aligned
            selects overlap the trigger when the selected row fits above it,
            then fall back below when another row would cross the viewport
            edge. This title-bar selector is consistently a dropdown instead. */}
        <SelectContent align="start" alignItemWithTrigger={false}>
          <SelectGroup>
            {items.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </span>
  );
}

/** The control panel's body: the app's generated GUI. Shared by both panel
 * chromes (the phone's bottom sheet and the desktop ControlPanelFrame), which
 * each hide it while collapsed. The browser's own settings are not in here:
 * they open in a popout off the header. */
export function ControlPanelContents() {
  return (
    <div data-leika-generated-gui>
      <MemoizedGeneratedGuiContainer containerUuid={ROOT_GUI_CONTAINER_ID} />
    </div>
  );
}

/** The phone's control panel: a bottom sheet. Desktop uses ControlPanelFrame;
 * App renders this only in the mobile view.
 *
 * The page name, sheet collapse, connection badge, and settings gear are four
 * independent controls. BottomPanel keeps the collapse button beside the
 * header rather than wrapping these other buttons in it. */
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

/** The panel header's contents: the active page on the left, the
 * connection and page-readiness status on the right, and whatever the chrome
 * around it wants between the two. */
export function PanelHeader({
  actions,
  badge = <ConnectionBadge />,
}: {
  actions?: React.ReactNode;
  /** The connection badge, or `null` where the header is itself inside a
   * button and cannot hold one. */
  badge?: React.ReactNode;
}) {
  return (
    <div
      // Match a GUI row's 24px frame so the title-to-first-row rhythm is the
      // same as the rhythm between rows, even though the header actions are
      // only 20px tall.
      className="flex min-h-6 min-w-0 flex-1 items-center gap-2"
      // What the settings popout aligns to: the gear is a 20px circle in the
      // middle of this row, and a popout hung off it would sit wherever the
      // title's length left it. See SettingsButton.
      data-leika-panel-header
    >
      <PageSelector />
      {/* A deliberate patch of title-bar surface beside the page name. With a
          choice of pages the name opens its menu; this sibling keeps moving
          and folding the panel available without asking users to aim between
          glyphs. */}
      <span
        className="min-w-2 flex-1 self-stretch"
        aria-hidden="true"
        data-leika-panel-drag-space
      />
      {actions}
      {/* The badge is a button onto what the connection is doing, in the one
          place a reader looks whether or not the panel is collapsed. */}
      {badge}
    </div>
  );
}
