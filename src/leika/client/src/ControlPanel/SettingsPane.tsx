import { RotateCcwIcon, SettingsIcon } from "lucide-react";
import * as React from "react";

import { commandPalette } from "../CommandPaletteController";
import { ImageFit } from "../ClientSettings";
import { ViewerContext } from "../ViewerContext";
import { ColorPickerPopover } from "../components/ColorPicker";
import { guiLabelClassName } from "../components/guiLabelStyles";
import { Button } from "../components/ui/button";
import { Collapsible, CollapsibleContent } from "../components/ui/collapsible";
import { Label } from "../components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { Switch } from "../components/ui/switch";
import { cn } from "@/lib/utils";
import { settingsPanel, useSettingsPanelOpen } from "./SettingsPanelController";

/** Ties the gear to the section it opens, for assistive technology. */
const SETTINGS_SECTION_ID = "leika-settings";

/** The accent a viewer lands on when they first open the picker: the theme's
 * own near-black, so the square opens where the app already is rather than
 * jumping to an arbitrary color. */
const DEFAULT_ACCENT = "rgb(38, 38, 38)";

/** One labelled row, on the same fixed label column as the generated GUI rows
 * below it, so the panel reads as one grid from its first row to its last.
 * Kept alongside `GuiInputRow` rather than reusing it: that one marks itself as
 * a row of the server's GUI, which these are not. */
function SettingsRow({
  htmlFor,
  label,
  children,
}: {
  htmlFor: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="grid min-h-6 grid-cols-[6rem_minmax(0,1fr)] items-center gap-2"
      data-leika-settings-row
    >
      <Label
        htmlFor={htmlFor}
        className={cn("w-full min-w-0 truncate", guiLabelClassName)}
        title={label}
      >
        {label}
      </Label>
      {children}
    </div>
  );
}

/** The accent swatch, opening the same picker every other color in the app
 * uses, and the reset that puts the theme's own accent back. */
function AccentColorRow() {
  const viewer = React.useContext(ViewerContext)!;
  const accentColor = viewer.useSettings((state) => state.accentColor);
  const { setAccentColor } = viewer.settingsActions;

  return (
    <SettingsRow htmlFor="leika-settings-accent" label="Accent color">
      <div className="gui-row-controls flex min-w-0 items-center gap-1">
        <ColorPickerPopover
          id="leika-settings-accent"
          label="Accent color"
          format="rgb"
          // Unset, the swatch shows the accent the theme is already using and
          // says so, rather than naming a color nobody chose.
          value={accentColor ?? DEFAULT_ACCENT}
          text={accentColor ?? "Default"}
          onValueChange={setAccentColor}
        />
        {accentColor === null ? null : (
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label="Reset accent color"
            onClick={() => setAccentColor(null)}
            data-leika-settings-accent-reset
          >
            <RotateCcwIcon />
          </Button>
        )}
      </div>
    </SettingsRow>
  );
}

/** How an image pane sizes itself, for panes whose app left it open. The same
 * three names Python's `fit` takes, capitalized. */
const IMAGE_FIT_LABELS: Record<ImageFit, string> = {
  fit: "Fit",
  fill: "Fill",
  stretch: "Stretch",
};

const IMAGE_FIT_ITEMS = (Object.keys(IMAGE_FIT_LABELS) as ImageFit[]).map(
  (value) => ({ value, label: IMAGE_FIT_LABELS[value] }),
);

function ImageFitRow() {
  const viewer = React.useContext(ViewerContext)!;
  const imageFit = viewer.useSettings((state) => state.imageFit);
  const { setImageFit } = viewer.settingsActions;

  return (
    <SettingsRow htmlFor="leika-settings-image-fit" label="Image fit">
      <div className="gui-row-controls flex min-w-0 items-center">
        <Select
          items={IMAGE_FIT_ITEMS}
          value={imageFit}
          onValueChange={(next) => next !== null && setImageFit(next)}
        >
          <SelectTrigger
            id="leika-settings-image-fit"
            className="w-full"
            data-leika-settings-image-fit
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {IMAGE_FIT_ITEMS.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
    </SettingsRow>
  );
}

/** Display preferences, revealed at the top of the control panel.
 *
 * It reads as part of the panel rather than a layer over it, unfolding on the
 * same height transition the GUI's own sections use. There is no header of its
 * own: the gear is its only handle, and a second one in the body would be a
 * second thing to keep in sync. Its open state lives outside React because that
 * gear sits in the panel header, which the dock mounts separately from the
 * body. */
export function SettingsSection() {
  const viewer = React.useContext(ViewerContext)!;
  const opened = useSettingsPanelOpen();
  const darkMode = viewer.useSettings((state) => state.darkMode);
  const showPaneTitles = viewer.useSettings((state) => state.showPaneTitles);
  const { setDarkMode, setShowPaneTitles } = viewer.settingsActions;
  // The switch shows the scheme in force, which until it is touched is the one
  // the server or the OS chose.
  const resolvedDarkMode =
    darkMode ?? document.documentElement.classList.contains("dark");
  // The palette renders nothing without commands, and closes itself when the
  // last one goes away, so opening it from here would look like a dead button.
  const commandCount = viewer.useGui(
    (state) => Object.keys(state.commands).length,
  );

  return (
    <Collapsible open={opened}>
      {/* The height transition the panel's sections use: the panel reports its
          own height as a variable, and the starting and ending styles give the
          transition somewhere to run from and to.

          The rule at the bottom is the one line in the panel that runs the
          body's full width: it separates the browser's controls from the
          server's, a bigger break than anything inside the GUI, so it crosses
          the padding the rows stop at instead of aligning with them.

          The pull-out and the padding that puts the rows back both belong on
          THIS element rather than a child of it, because the height transition
          needs `overflow-hidden` and that clips anything reaching past its
          edges -- a child would keep its full-width layout box and still be
          painted short. */}
      <CollapsibleContent
        id={SETTINGS_SECTION_ID}
        className="-mx-(--card-spacing) h-(--collapsible-panel-height) overflow-hidden border-b px-(--card-spacing) transition-[height] duration-200 ease-out data-ending-style:h-0 data-starting-style:h-0"
      >
        <div className="flex flex-col gap-2 pt-2 pb-3" data-leika-settings-pane>
          <SettingsRow htmlFor="leika-settings-dark-mode" label="Dark mode">
            <Switch
              id="leika-settings-dark-mode"
              className="justify-self-start"
              checked={resolvedDarkMode}
              onCheckedChange={setDarkMode}
            />
          </SettingsRow>
          <SettingsRow htmlFor="leika-settings-pane-titles" label="Pane titles">
            <Switch
              id="leika-settings-pane-titles"
              className="justify-self-start"
              checked={showPaneTitles}
              onCheckedChange={setShowPaneTitles}
            />
          </SettingsRow>
          <AccentColorRow />
          <ImageFitRow />
          <Button
            variant="outline"
            className="h-7 w-full"
            disabled={commandCount === 0}
            onClick={() => commandPalette.open()}
            data-leika-settings-commands
          >
            Open command palette
          </Button>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

/** The gear that opens the settings, sized to sit beside the status pill. */
export function SettingsButton() {
  const { useGui } = React.useContext(ViewerContext)!;
  const connected = useGui((state) => state.websocketState === "connected");
  const opened = useSettingsPanelOpen();

  // Closed on the way down, not merely locked: leaving the pane open behind a
  // disabled gear would strand it, with nothing left that could fold it away.
  React.useEffect(() => {
    if (!connected) settingsPanel.close();
  }, [connected]);

  return (
    // The panel header is the floating window's drag handle and its
    // click-to-collapse target, both driven from `pointerdown`, so the gesture
    // that opens the section must not also reach it.
    <span
      className="inline-flex"
      onPointerDown={(event) => event.stopPropagation()}
    >
      <Button
        // Circular, and the same 20px height as the status badge beside it, so
        // the two read as one cluster in the header. Idle, the gear is typed
        // like the pill's own label rather than a step darker, so the pair
        // reads as one weight.
        //
        // Open, it fills with the accent the same way a checked checkbox or a
        // filled slider does -- `default` IS that pair of tokens, so an accent
        // set below reaches the gear that opened the pane without being told.
        variant={opened ? "default" : "secondary"}
        size="icon-xs"
        className={cn(
          "size-5 rounded-full",
          !opened && "text-muted-foreground",
        )}
        aria-label="Settings"
        aria-expanded={opened}
        aria-controls={SETTINGS_SECTION_ID}
        // Nothing in here is worth reading off a page that has stopped
        // tracking its server, so it goes with the connection.
        disabled={!connected}
        onClick={() => settingsPanel.toggle()}
        data-leika-settings-trigger
      >
        <SettingsIcon />
      </Button>
    </span>
  );
}
