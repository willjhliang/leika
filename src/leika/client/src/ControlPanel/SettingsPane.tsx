import { SettingsIcon } from "lucide-react";
import * as React from "react";

import { commandPalette } from "../CommandPaletteController";
import { ImageFit } from "../ClientSettings";
import { LEIKA_VERSION } from "../VersionInfo";
import { ViewerContext } from "../ViewerContext";
import { ColorRow } from "../components/ColorPicker";
import {
  guiLabelClassName,
  guiRowGridClassName,
} from "../components/guiLabelStyles";
import { Button } from "../components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "../components/ui/popover";
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
import { POPOUT_WIDTH_CLASS } from "./controlWidth";

/** Names the popout the gear opens, for assistive technology. */
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
    <div className={cn(guiRowGridClassName, "gap-2")} data-leika-settings-row>
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
      <ColorRow
        id="leika-settings-accent"
        label="Accent color"
        format="rgb"
        // Unset, the swatch shows the accent the theme is already using and
        // says so, rather than naming a color nobody chose.
        value={accentColor ?? DEFAULT_ACCENT}
        text={accentColor ?? "Default"}
        className="gui-row-controls"
        // Undo means no accent at all, which is what puts the theme's back.
        onReset={accentColor === null ? null : () => setAccentColor(null)}
        onValueChange={setAccentColor}
      />
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

const REPOSITORY_URL = "https://github.com/willjhliang/leika";
const DOCUMENTATION_URL = "https://willjhliang.github.io/leika/";
const EXAMPLES_URL = "https://github.com/willjhliang/leika/tree/main/examples";

/** One word of the footer sentence that goes somewhere.
 *
 * External destinations out of an app holding live state, so they open beside
 * the workspace rather than navigating away from it and losing the session. */
function FooterLink({
  href,
  attrs,
  children,
}: {
  href: string;
  attrs: Record<string, string>;
  children: React.ReactNode;
}) {
  return (
    <a
      {...attrs}
      href={href}
      target="_blank"
      rel="noreferrer"
      className="underline underline-offset-2 hover:text-foreground"
    >
      {children}
    </a>
  );
}

/** The footer of the browser's own controls: what a viewer would be asked to
 * quote in a bug report, and the three places to go next.
 *
 * The version is the client's, baked in at build time, which is the one worth
 * printing: the server refuses a client whose version differs from its own, so
 * a client that is connected at all agrees with Python.
 *
 * Selectable, so it can be copied into a report rather than retyped. */
function AboutRow() {
  return (
    // A sentence rather than a row of parts, so it stays on one line by being
    // short enough to need no arranging.
    <div
      className="pt-0.5 text-center text-xs text-muted-foreground select-text"
      data-leika-settings-about
    >
      <span data-leika-settings-version>Leika v{LEIKA_VERSION}</span>.{" "}
      <FooterLink
        href={REPOSITORY_URL}
        attrs={{ "data-leika-settings-source": "true" }}
      >
        Source
      </FooterLink>
      ,{" "}
      <FooterLink
        href={DOCUMENTATION_URL}
        attrs={{ "data-leika-settings-docs": "true" }}
      >
        docs
      </FooterLink>
      , and{" "}
      <FooterLink
        href={EXAMPLES_URL}
        attrs={{ "data-leika-settings-examples": "true" }}
      >
        examples
      </FooterLink>
      .
    </div>
  );
}

/** Display preferences, in the popout the gear opens.

 * A popout rather than a section of the panel: these are the browser's
 * settings, not the app's controls, and a band of them wedged in above the
 * app's own rows read as more of the panel -- the one thing it is not. Off to
 * the side it is plainly a thing apart, the way a color picker or a form is,
 * and the panel underneath is left whole.
 */
function SettingsRows() {
  const viewer = React.useContext(ViewerContext)!;
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
    <div className="flex flex-col gap-2" data-leika-settings-pane>
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
      {/* A step clear of the fields: it does not set a preference, it opens
          something else. */}
      <Button
        variant="outline"
        className="mt-2 h-7 w-full"
        disabled={commandCount === 0}
        onClick={() => commandPalette.open()}
        data-leika-settings-commands
      >
        Open command palette
      </Button>
      <AboutRow />
    </div>
  );
}

export function SettingsButton() {
  const { useGui } = React.useContext(ViewerContext)!;
  const connected = useGui((state) => state.websocketState === "connected");
  const opened = useSettingsPanelOpen();

  const gear = React.useRef<HTMLSpanElement>(null);

  // Closed on the way down, not merely locked: leaving the popout open behind
  // a disabled gear would strand it, with nothing left that could close it.
  React.useEffect(() => {
    if (!connected) settingsPanel.close();
  }, [connected]);

  return (
    // The panel header is the floating window's drag handle and its
    // click-to-collapse target, both driven from `pointerdown`, so the gesture
    // that opens the popout must not also reach it.
    <span
      ref={gear}
      className="inline-flex"
      onPointerDown={(event) => event.stopPropagation()}
    >
      {/* Open state stays in the shared controller rather than in this
          component: the gear is mounted by the panel HEADER, which the dock
          registers separately from the body, and other parts of the panel read
          whether the settings are up. */}
      <Popover
        open={opened}
        onOpenChange={(next) =>
          next ? settingsPanel.open() : settingsPanel.close()
        }
      >
        <PopoverTrigger
          render={
            <Button
              // Circular, and the same 20px height as the status badge beside
              // it, so the two read as one cluster in the header. Idle, the
              // gear is typed like the pill's own label rather than a step
              // darker, so the pair reads as one weight.
              //
              // Open, it fills with the accent the same way a checked checkbox
              // or a filled slider does -- `default` IS that pair of tokens, so
              // an accent set inside reaches the gear that opened it without
              // being told.
              variant={opened ? "default" : "secondary"}
              size="icon-xs"
              className={cn(
                "size-5 rounded-full",
                !opened && "text-muted-foreground",
              )}
              aria-label="Settings"
              // Nothing in here is worth reading off a page that has stopped
              // tracking its server, so it goes with the connection.
              disabled={!connected}
              data-leika-settings-trigger
            />
          }
        >
          <SettingsIcon />
        </PopoverTrigger>
        <PopoverContent
          id={SETTINGS_SECTION_ID}
          align="end"
          // Aligned to the HEADER, not to the gear: every other popout in the
          // panel hangs off a row and lines up with that row's end, which is
          // the panel's own edge. The gear is a 20px circle somewhere in the
          // middle of its row, so aligning to it would put the popout wherever
          // the title's length happened to leave it -- a different place in
          // every app. The header row ends where the rows below it do.
          anchor={() =>
            gear.current?.closest("[data-leika-panel-header]") ?? gear.current
          }
          className={POPOUT_WIDTH_CLASS}
          data-leika-settings-popover
        >
          {/* Named out loud. A popout that arrives beside the panel rather
              than in it has nothing around it to say what it is, and the gear
              that opened it is a 20px circle the pointer has already left. */}
          <PopoverHeader>
            <PopoverTitle data-leika-settings-title>Settings</PopoverTitle>
            <PopoverDescription className="sr-only">
              Display preferences for this browser.
            </PopoverDescription>
          </PopoverHeader>
          <SettingsRows />
        </PopoverContent>
      </Popover>
    </span>
  );
}
