// Dev-only gallery of every popup the app can put on screen. Served by the
// Vite dev server at /popup_test.html; not part of the production bundle
// (which only inputs index.html). Run `vite` and open
// http://localhost:3000/popup_test.html.
//
// One page holding all of them, because that is what a change to how popups
// are styled has to be judged against: a radius or a shadow that reads well on
// a dialog can be wrong on a tooltip, and the two are never on screen together
// anywhere in the real app. Each specimen names the file it is drawn by, so a
// look worth changing can be traced back to the one place that sets it.
//
// The specimens use the shared components wherever a shared component exists
// (`MediaPreview`, `FilePreviewDialog`, `ColorRow`, `HintTooltip`, the toast
// manager). Where the app composes ui primitives inline -- the GUI modal, the
// popouts, the dropdowns -- so does this, mirroring the call site rather than
// importing something the app does not have.

/* eslint-disable react-refresh/only-export-components -- standalone dev entry. */
import "./index.css";
import {
  ClipboardPen,
  DownloadIcon,
  ImageIcon,
  PaletteIcon,
  PlayIcon,
  SettingsIcon,
  TrashIcon,
} from "lucide-react";
import * as React from "react";
import ReactDOM from "react-dom/client";

import { Button } from "@/components/ui/button";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
  ComboboxValue,
} from "@/components/ui/combobox";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Status, StatusIndicator, StatusLabel } from "@/components/ui/status";
import { Switch } from "@/components/ui/switch";
import { Toaster, toast } from "@/components/ui/toast";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { ColorRow } from "./components/ColorPicker";
import { GuiInputRow, HintTooltip } from "./components/common";
import { FilePreviewDialog } from "./components/FilePreviewDialog";
import {
  guiLabelClassName,
  guiRowGridClassName,
} from "./components/guiLabelStyles";
import { MediaPreview } from "./components/MediaPreview";
import { mediaPreviewWidth, useMediaSize } from "./components/mediaPreviewSize";
import {
  previewMediaClassName,
  usePreviewFullscreen,
} from "./components/previewFullscreen";
import { POPOUT_WIDTH_CLASS } from "./ControlPanel/controlWidth";
import type { FilePreview } from "./filePreview";
import { usePrefersDarkMode } from "./hooks/useMediaQuery";

/* -------------------------------------------------------------------------- */
/* Page furniture                                                             */
/* -------------------------------------------------------------------------- */

/** A group of specimens that share a surface. */
function Section({
  title,
  blurb,
  children,
}: {
  title: string;
  blurb: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h2 className="cn-font-heading text-base leading-none font-medium">
          {title}
        </h2>
        <p className="text-sm text-muted-foreground">{blurb}</p>
      </div>
      <div className="flex flex-col gap-2">{children}</div>
    </section>
  );
}

/** One popup, with what opens it on the right.
 *
 * `source` is the file that decides how this specimen looks -- the one to open
 * when it should look like something else. */
function Specimen({
  name,
  source,
  children,
}: {
  name: string;
  source: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-4 rounded-lg border border-border p-3">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="text-sm">{name}</p>
        <p className="truncate font-mono text-xs text-muted-foreground">
          {source}
        </p>
      </div>
      {/* Marked, because two of the popouts align to the panel's EDGE rather
          than to the small control that opens them. This column's end is the
          nearest thing here to that edge, and they find it the same way the
          real ones find the panel header: by asking for it. */}
      <div className="flex w-56 shrink-0 justify-end" data-specimen-controls>
        {children}
      </div>
    </div>
  );
}

/** The scheme the page is drawn in.
 *
 * The same three states the settings pane offers, for the same reason: a popup
 * has to be judged in both themes, and "auto" is what the real page does when
 * no one has chosen. */
type Scheme = "auto" | "light" | "dark";

const SCHEME_ITEMS: { value: Scheme; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

function useScheme(): [Scheme, (next: Scheme) => void] {
  const prefersDark = usePrefersDarkMode();
  const [scheme, setScheme] = React.useState<Scheme>("auto");
  const dark = scheme === "auto" ? prefersDark : scheme === "dark";
  React.useLayoutEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.classList.toggle("light", !dark);
  }, [dark]);
  return [scheme, setScheme];
}

/* -------------------------------------------------------------------------- */
/* Sample content                                                             */
/* -------------------------------------------------------------------------- */

/** A handful of GUI rows, standing in for the components a server puts inside
 * a modal or a form. The popup is what is being looked at; these are only what
 * gives it something to be the size of. */
function SampleGuiRows({ prefix }: { prefix: string }) {
  const [text, setText] = React.useState("run-0142");
  const [scale, setScale] = React.useState("Medium");
  const [live, setLive] = React.useState(true);
  return (
    <>
      <GuiInputRow uuid={`${prefix}-name`} label="Run name">
        <Input
          id={`${prefix}-name`}
          className="h-6"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      </GuiInputRow>
      <GuiInputRow uuid={`${prefix}-scale`} label="Scale" hint="How big.">
        <Select
          items={["Small", "Medium", "Large"].map((value) => ({
            value,
            label: value,
          }))}
          value={scale}
          onValueChange={(next) => next !== null && setScale(next)}
        >
          <SelectTrigger id={`${prefix}-scale`} className="h-6 w-full">
            <SelectValue className="block! min-w-0 truncate" />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {["Small", "Medium", "Large"].map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </GuiInputRow>
      <GuiInputRow uuid={`${prefix}-live`} label="Stream results">
        <Switch
          id={`${prefix}-live`}
          className="justify-self-start"
          checked={live}
          onCheckedChange={setLive}
        />
      </GuiInputRow>
    </>
  );
}

/** A picture, drawn rather than fetched: a dev page that reaches for the
 * network is a dev page that stops working offline.
 *
 * Sized by its caller, because the shape is the point: a media preview takes
 * the width of what is in it, and only a picture that is NOT the shape of the
 * popup shows whether that is true. */
function sampleCanvas(width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d")!;
  const fill = ctx.createLinearGradient(0, 0, width, height);
  fill.addColorStop(0, "#1d4ed8");
  fill.addColorStop(0.55, "#7c3aed");
  fill.addColorStop(1, "#db2777");
  ctx.fillStyle = fill;
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(255, 255, 255, 0.22)";
  ctx.lineWidth = 1;
  for (let x = 60; x < width; x += 60) {
    ctx.beginPath();
    ctx.moveTo(x + 0.5, 0);
    ctx.lineTo(x + 0.5, height);
    ctx.stroke();
  }
  for (let y = 60; y < height; y += 60) {
    ctx.beginPath();
    ctx.moveTo(0, y + 0.5);
    ctx.lineTo(width, y + 0.5);
    ctx.stroke();
  }
  ctx.fillStyle = "rgba(255, 255, 255, 0.92)";
  ctx.font = "500 30px sans-serif";
  ctx.fillText(`${width} × ${height}`, 44, 72);
  return canvas;
}

const LANDSCAPE = { width: 960, height: 600 };
const PORTRAIT = { width: 520, height: 900 };

const dataUrls = new Map<string, string>();
function sampleImageDataUrl({ width, height }: typeof LANDSCAPE): string {
  const key = `${width}x${height}`;
  let url = dataUrls.get(key);
  if (url === undefined) {
    url = sampleCanvas(width, height).toDataURL("image/png");
    dataUrls.set(key, url);
  }
  return url;
}

function samplePngBlob({ width, height }: typeof LANDSCAPE): Promise<Blob> {
  return new Promise((resolve) =>
    sampleCanvas(width, height).toBlob((blob) => resolve(blob!), "image/png"),
  );
}

const SAMPLE_MARKDOWN = `# Training report

A document previewed as **markdown**: headings, prose, code and a table, so
the reading column can be judged against every block a real report holds.

## Setup

The sweep ran on a single node. Each configuration was given the same seed,
and the checkpoint with the lowest validation loss was kept.

\`\`\`python
import leika

server = leika.Server()
server.gui.add_markdown("Some **markdown**.")
\`\`\`

| Run | Steps | Loss | Notes |
| --- | ----- | ---- | ----- |
| a-01 | 12,000 | 0.418 | baseline |
| a-02 | 12,000 | 0.371 | warmup doubled |
| a-03 | 24,000 | 0.352 | best |

> A blockquote, for the aside that did not fit in the paragraph above it.

See the [documentation](https://willjhliang.github.io/leika/) for the rest.

- A list item.
- Another, longer, so the measure has something to wrap against and the eye
  has to find the start of the next line the way it does in real prose.

## Results

The headings from here on are what the contents list in the margin is made
of, so there are enough of them to judge one by.

### Validation loss

Lower throughout, and lowest at the doubled warmup.

### Throughput

Unchanged, which was the point: the warmup costs nothing at steady state.

## What is left

A heading long enough to wrap in a fourteen-rem column, which is a thing a
contents list has to do gracefully.
`;

const SAMPLE_LOG = Array.from(
  { length: 60 },
  (_, i) =>
    `2026-08-06T09:${String(12 + Math.floor(i / 6)).padStart(2, "0")}:${String(
      (i * 7) % 60,
    ).padStart(2, "0")}Z  step=${(i + 1) * 200}  loss=${(
      1.9 * Math.exp(-i / 18)
    ).toFixed(4)}  lr=3.0e-4  throughput=${1180 + ((i * 37) % 90)} tok/s`,
).join("\n");

const SAMPLE_PROSE = `Plain text, which is what a .txt is: writing nobody has
typeset, so the lines are the author's and it is set in monospace rather than
rendered.

It wraps rather than scrolls, because a paragraph is not a record. The measure
is the same one a markdown document is read at, so switching between the two
does not move the column.
`;

/** Build a preview whose bytes are already in hand. */
function previewOf(
  id: string,
  filename: string,
  mimeType: string,
  body: BlobPart,
): FilePreview {
  const blob = new Blob([body], { type: mimeType });
  return {
    id,
    filename,
    mimeType,
    sizeBytes: blob.size,
    contents: { blob, url: URL.createObjectURL(blob) },
    // Named so the reload corner is drawn: in the app this is the button the
    // file came out of. No version, which is what a source that cannot change
    // looks like -- and the gallery has no server to watch one anyway.
    sourceUuid: id,
    sourceVersion: null,
  };
}

/* -------------------------------------------------------------------------- */
/* Dialogs                                                                    */
/* -------------------------------------------------------------------------- */

/** The dialog `add_modal` opens, drawn the way `Modal.tsx` draws it: a title,
 * the server's components, and a backdrop that dismisses on a click outside. */
function GuiModal({
  open,
  onOpenChange,
  title,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">{children}</div>
      </DialogContent>
    </Dialog>
  );
}

function ModalSpecimen() {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        Open modal
      </Button>
      <GuiModal open={open} onOpenChange={setOpen} title="Launch a sweep">
        <SampleGuiRows prefix="modal" />
        <Button className="mt-2 w-full" onClick={() => setOpen(false)}>
          <PlayIcon data-icon="inline-start" />
          Launch
        </Button>
      </GuiModal>
    </>
  );
}

/** Two modals at once, which the protocol allows: `add_modal` can be called
 * again while one is up. The later portal and backdrop own the top layer. */
function StackedModalSpecimen() {
  const [depth, setDepth] = React.useState(0);
  return (
    <>
      <Button variant="outline" onClick={() => setDepth(1)}>
        Open two
      </Button>
      {/* The one underneath is the taller of the two, so that it is visible
          around the second rather than exactly behind it. A modal is the size
          of what the server put in it, so two of them rarely match. */}
      <GuiModal
        open={depth >= 1}
        onOpenChange={(next) => !next && setDepth(0)}
        title="First modal"
      >
        <p className="text-muted-foreground">
          Its surface stays mounted while the second dialog and its backdrop
          take the top layer.
        </p>
        <SampleGuiRows prefix="stacked-first" />
        <Button
          variant="outline"
          className="mt-2 w-full"
          onClick={() => setDepth(2)}
        >
          Open the second
        </Button>
      </GuiModal>
      <GuiModal
        open={depth >= 2}
        onOpenChange={(next) => !next && setDepth(1)}
        title="Second modal"
      >
        <p className="text-muted-foreground">
          Dismissed on its own — Escape closes the innermost open thing and
          returns to the first.
        </p>
      </GuiModal>
    </>
  );
}

const PALETTE_ACTIONS = [
  { id: "reset", label: "Reset camera", shortcut: "⌘⇧R", icon: <PlayIcon /> },
  {
    id: "export",
    label: "Export scene…",
    shortcut: "⌘E",
    icon: <DownloadIcon />,
  },
  { id: "screenshot", label: "Take screenshot", icon: <ImageIcon /> },
  { id: "theme", label: "Toggle color scheme", icon: <PaletteIcon /> },
  {
    id: "settings",
    label: "Open settings",
    shortcut: "⌘,",
    icon: <SettingsIcon />,
  },
  {
    id: "clear",
    label: "Clear every pane in the workspace",
    icon: <TrashIcon />,
  },
];

/** The palette, as `CommandPalette.tsx` opens it. Filtering is cmdk's own here
 * rather than the app's fuzzy match: what is on show is the popup, and its
 * empty state needs a query that matches nothing to be seen at all. */
function CommandPaletteSpecimen() {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        Open palette
      </Button>
      <CommandDialog
        open={open}
        onOpenChange={setOpen}
        title="Commands"
        description="Search for a registered Leika command."
      >
        <Command label="Search commands">
          <CommandInput
            aria-label="Search commands"
            placeholder="Search commands..."
          />
          <CommandList>
            <CommandEmpty>No matching commands...</CommandEmpty>
            <CommandGroup heading="Commands">
              {PALETTE_ACTIONS.map((action) => (
                <CommandItem
                  key={action.id}
                  value={action.label}
                  onSelect={() => setOpen(false)}
                >
                  {action.icon}
                  <span className="min-w-0 flex-1 truncate">
                    {action.label}
                  </span>
                  {action.shortcut ? (
                    <CommandShortcut>{action.shortcut}</CommandShortcut>
                  ) : null}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </CommandDialog>
    </>
  );
}

/** A media preview opened from a pane, as `Image.tsx` opens it: the popup is
 * the width of the picture, measured off the same hook the app uses.
 *
 * Two shapes, because that is what the sizing is for. The portrait one is the
 * case a fixed frame got wrong -- it used to open in the document's width with
 * a column of empty dialog down either side of it.
 *
 * They remember "fill the window" separately, which is worth trying here: it
 * is the behaviour a single specimen could not show. */
function MediaPreviewSpecimen({ shape }: { shape: typeof LANDSCAPE }) {
  const [open, setOpen] = React.useState(false);
  const url = sampleImageDataUrl(shape);
  const size = useMediaSize(url);
  const key = `demo-pane-${shape.width}x${shape.height}`;
  const [fullscreen] = usePreviewFullscreen(key);
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        Expand
      </Button>
      <MediaPreview
        open={open}
        onOpenChange={setOpen}
        title="Rendered frame"
        rememberAs={key}
        width={mediaPreviewWidth(size)}
      >
        <img src={url} alt="" className={previewMediaClassName(fullscreen)} />
      </MediaPreview>
    </>
  );
}

/** Every viewer a previewed file can land in, plus the popup while it is still
 * arriving. One dialog at a time, which is what the real store enforces.
 *
 * The image lands in the SAME popup the two specimens above it open -- a
 * media preview, sized to the picture -- while everything else here gets the
 * document frame. That split is the whole of what separates these from a
 * pane's expand button. */
function FilePreviewSpecimens() {
  const [preview, setPreview] = React.useState<FilePreview | null>(null);

  const close = () => {
    if (preview?.contents !== null && preview?.contents !== undefined) {
      URL.revokeObjectURL(preview.contents.url);
    }
    setPreview(null);
  };

  const trigger = (label: string, build: () => Promise<FilePreview>) => (
    <Button variant="outline" onClick={() => void build().then(setPreview)}>
      {label}
    </Button>
  );

  // In the app a press asks the server for the file again and the answer
  // arrives as new contents. Here it answers itself with the same bytes in a
  // new wrapper, which is all the dialog watches for to stop its spinner --
  // so the corner behaves, and there is a gallery of it to style against.
  const reload = () =>
    setPreview((current) =>
      current === null || current.contents === null
        ? current
        : { ...current, contents: { ...current.contents } },
    );

  return (
    <>
      <Specimen
        name="File preview — image, a media preview like the two above"
        source="FilePreviewDialog.tsx"
      >
        {trigger("Preview .png", async () => {
          const blob = await samplePngBlob(PORTRAIT);
          return {
            id: "png",
            filename: "frame-0042.png",
            mimeType: "image/png",
            sizeBytes: blob.size,
            contents: { blob, url: URL.createObjectURL(blob) },
            sourceUuid: "png",
            sourceVersion: null,
          };
        })}
      </Specimen>
      <Specimen
        name="File preview — markdown document"
        source="FilePreviewDialog.tsx"
      >
        {trigger("Preview .md", async () =>
          previewOf("md", "report.md", "text/markdown", SAMPLE_MARKDOWN),
        )}
      </Specimen>
      <Specimen name="File preview — plain text" source="FilePreviewDialog.tsx">
        {trigger("Preview .txt", async () =>
          previewOf("txt", "notes.txt", "text/plain", SAMPLE_PROSE),
        )}
      </Specimen>
      <Specimen
        name="File preview — log, records not prose"
        source="FilePreviewDialog.tsx"
      >
        {trigger("Preview .log", async () =>
          previewOf(
            "log",
            "train.log",
            "text/plain; charset=utf-8",
            SAMPLE_LOG,
          ),
        )}
      </Specimen>
      <Specimen
        name="File preview — nothing can open it"
        source="FilePreviewDialog.tsx"
      >
        {trigger("Preview .bin", async () =>
          previewOf(
            "bin",
            "checkpoint.bin",
            "application/octet-stream",
            new Uint8Array(4096),
          ),
        )}
      </Specimen>
      <Specimen
        name="File preview — file still arriving"
        source="FilePreviewDialog.tsx"
      >
        <Button
          variant="outline"
          onClick={() =>
            setPreview({
              id: "pending",
              filename: "checkpoint-final.safetensors",
              mimeType: "application/octet-stream",
              sizeBytes: 1_482_391_552,
              contents: null,
              // No corner chrome but the close while the file is still on its
              // way: nothing to save, and nothing to ask for twice.
              sourceUuid: "pending",
              sourceVersion: null,
            })
          }
        >
          Preview pending
        </Button>
      </Specimen>
      {preview === null ? null : (
        <FilePreviewDialog
          key={preview.id}
          preview={preview}
          onClose={close}
          onReload={reload}
        />
      )}
    </>
  );
}

/** The stock dialog, with the description and footer the kit draws and the app
 * has so far had no use for. Here because a change to `dialog.tsx` reaches
 * them, and there is otherwise nowhere to see it land. */
function StockDialogSpecimen() {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        Open dialog
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Discard this layout?</DialogTitle>
            <DialogDescription>
              The panes go back to where the app put them. Nothing else about
              the session changes.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              Cancel
            </DialogClose>
            <Button onClick={() => setOpen(false)}>Discard</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Popovers                                                                   */
/* -------------------------------------------------------------------------- */

/** One row of the settings popout: a fixed label column beside its control,
 * matching `SettingsPane.tsx`. */
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
    <div className={cn(guiRowGridClassName, "gap-2")}>
      <Label
        htmlFor={htmlFor}
        className={cn("w-full min-w-0 truncate", guiLabelClassName)}
      >
        {label}
      </Label>
      {children}
    </div>
  );
}

/** The popout the gear opens: a named header over the browser's own settings,
 * aligned to the panel's edge. */
function SettingsPopoutSpecimen() {
  const [open, setOpen] = React.useState(false);
  const [titles, setTitles] = React.useState(true);
  const [accent, setAccent] = React.useState<string | null>(null);
  const [fit, setFit] = React.useState("Fit");
  const gear = React.useRef<HTMLButtonElement>(null);
  const fitItems = ["Fit", "Fill", "Stretch"].map((value) => ({
    value,
    label: value,
  }));
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            ref={gear}
            variant={open ? "default" : "secondary"}
            size="icon-xs"
            className={cn(
              "size-5 rounded-full",
              !open && "text-muted-foreground",
            )}
            aria-label="Settings"
          />
        }
      >
        <SettingsIcon />
      </PopoverTrigger>
      <PopoverContent
        align="end"
        anchor={() =>
          gear.current?.closest("[data-specimen-controls]") ?? gear.current
        }
        className={POPOUT_WIDTH_CLASS}
      >
        <PopoverHeader>
          <PopoverTitle>Settings</PopoverTitle>
          <PopoverDescription className="sr-only">
            Display preferences for this browser.
          </PopoverDescription>
        </PopoverHeader>
        <div className="flex flex-col gap-2">
          <SettingsRow htmlFor="demo-fit" label="Image fit">
            <div className="gui-row-controls flex min-w-0 items-center">
              <Select
                items={fitItems}
                value={fit}
                onValueChange={(next) => next !== null && setFit(next)}
              >
                <SelectTrigger id="demo-fit" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {fitItems.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
          </SettingsRow>
          <SettingsRow htmlFor="demo-titles" label="Pane titles">
            <Switch
              id="demo-titles"
              className="justify-self-start"
              checked={titles}
              onCheckedChange={setTitles}
            />
          </SettingsRow>
          <SettingsRow htmlFor="demo-accent" label="Accent color">
            <ColorRow
              id="demo-accent"
              label="Accent color"
              format="rgb"
              value={accent ?? "rgb(38, 38, 38)"}
              text={accent ?? "Default"}
              className="gui-row-controls"
              onReset={accent === null ? null : () => setAccent(null)}
              onValueChange={setAccent}
            />
          </SettingsRow>
          <Button variant="outline" className="mt-2 h-7 w-full">
            Open command palette
          </Button>
          <div className="pt-0.5 text-center text-xs text-muted-foreground select-text">
            Leika v0.0.0. Source, documentation, and examples.
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}

/** One measurement in the connection popout. */
function StatRow({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className={cn(guiRowGridClassName, "gap-2")}>
      <span className={cn("w-full min-w-0 truncate", guiLabelClassName)}>
        {label}
      </span>
      <span className="min-w-0 truncate text-xs">
        {value}
        {detail === undefined ? null : (
          <span className="text-muted-foreground"> {detail}</span>
        )}
      </span>
    </div>
  );
}

/** The popout the connection badge opens: what this browser is measuring on
 * its link to the server. */
function ConnectionPopoutSpecimen() {
  const [open, setOpen] = React.useState(false);
  const badge = React.useRef<HTMLButtonElement>(null);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Status
            status="online"
            variant={open ? "default" : "secondary"}
            className={
              open
                ? "hover:bg-primary/80"
                : "hover:bg-[color-mix(in_oklch,var(--secondary),var(--foreground)_5%)]"
            }
            render={
              <button
                ref={badge}
                type="button"
                aria-label="Connection details"
              />
            }
          />
        }
      >
        <StatusIndicator />
        <StatusLabel className={open ? "text-primary-foreground" : undefined}>
          Connected
        </StatusLabel>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        anchor={() =>
          badge.current?.closest("[data-specimen-controls]") ?? badge.current
        }
        className={POPOUT_WIDTH_CLASS}
      >
        <PopoverHeader>
          <PopoverTitle>Connection</PopoverTitle>
          <PopoverDescription className="sr-only">
            What this browser is measuring on its link to the server.
          </PopoverDescription>
        </PopoverHeader>
        <div className="flex flex-col gap-2">
          <StatRow label="Quality" value="Good" />
          <StatRow label="Latency" value="12 ms" detail="(median 14 ms)" />
          <StatRow label="Down" value="184 kB/s" detail="(21.4 MB total)" />
          <StatRow label="Up" value="3.1 kB/s" detail="(412 kB total)" />
          <StatRow label="Messages" value="8,142 in, 903 out" />
          <StatRow label="Connected" value="14m 22s" detail="(1 reconnect)" />
          <div className="pt-0.5 text-center text-xs break-all text-muted-foreground select-text">
            ws://localhost:8080 (Protocol 0).
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}

/** The popout `add_form` opens: fields that are submitted together, with an
 * accessible name nothing on screen says out loud. */
function FormPopoutSpecimen() {
  const [open, setOpen] = React.useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger render={<Button variant="outline" className="w-full" />}>
        <ClipboardPen data-icon="inline-start" />
        Open form
      </PopoverTrigger>
      <PopoverContent align="end" className={POPOUT_WIDTH_CLASS}>
        <PopoverHeader className="sr-only">
          <PopoverTitle>Sweep settings</PopoverTitle>
          <PopoverDescription>
            Fill in the fields, then submit them together.
          </PopoverDescription>
        </PopoverHeader>
        <form
          className="flex w-full min-w-0 flex-col gap-2 [&>:last-child]:mt-2"
          onSubmit={(event) => {
            event.preventDefault();
            setOpen(false);
          }}
        >
          <button type="submit" hidden tabIndex={-1} />
          <SampleGuiRows prefix="form" />
          <Button type="submit" className="w-full">
            Submit
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}

/* -------------------------------------------------------------------------- */
/* Menus, tooltips, toasts                                                    */
/* -------------------------------------------------------------------------- */

const DROPDOWN_OPTIONS = [
  "Adam",
  "AdamW",
  "Lion",
  "RMSprop",
  "SGD with momentum",
  "Shampoo",
  "Sophia",
];

/** The default dropdown: a plain Select, which opens with the current option
 * already under the cursor. Mirrors `Dropdown.tsx`. */
function SelectSpecimen() {
  const [value, setValue] = React.useState("AdamW");
  const items = DROPDOWN_OPTIONS.map((option) => ({
    label: option,
    value: option,
  }));
  return (
    <Select
      items={items}
      value={value}
      onValueChange={(next) => next !== null && setValue(next)}
    >
      <SelectTrigger className="w-full">
        <SelectValue className="block! min-w-0 truncate" />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

/** The `searchable` dropdown: a Combobox, whose popup is a filter box over the
 * options. Mirrors `Dropdown.tsx`. */
function ComboboxSpecimen() {
  const [value, setValue] = React.useState("Lion");
  return (
    <Combobox
      items={DROPDOWN_OPTIONS}
      value={value}
      onValueChange={(next) => next !== null && setValue(next)}
      itemToStringLabel={(option) => option}
      itemToStringValue={(option) => option}
    >
      <ComboboxTrigger
        render={<Button variant="outline" className="w-full justify-between" />}
      >
        <ComboboxValue placeholder="Select…" />
      </ComboboxTrigger>
      <ComboboxContent>
        <ComboboxInput
          showTrigger={false}
          placeholder="Search…"
          aria-label="Search options"
        />
        <ComboboxEmpty>No options found.</ComboboxEmpty>
        <ComboboxList>
          {(option: string) => (
            <ComboboxItem key={option} value={option}>
              {option}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}

/** A tooltip on each side, so the arrow and the slide-in are visible in all
 * four directions at once. */
function TooltipSidesSpecimen() {
  const sides = ["top", "right", "bottom", "left"] as const;
  return (
    <div className="flex gap-1">
      {sides.map((side) => (
        <Tooltip key={side}>
          <TooltipTrigger render={<Button variant="outline" size="sm" />}>
            {side}
          </TooltipTrigger>
          <TooltipContent side={side}>Anchored {side}</TooltipContent>
        </Tooltip>
      ))}
    </div>
  );
}

/** The toasts a notification can be. `type` picks the icon; the app's own
 * protocol only ever asks for `loading` or none, but the kit draws all of
 * them and a change to `toast.tsx` reaches every one. */
function ToastSpecimens() {
  const rows: {
    name: string;
    label: string;
    add: () => void;
  }[] = [
    {
      name: "Notification — title only",
      label: "Show",
      add: () => toast.add({ title: "Checkpoint saved" }),
    },
    {
      name: "Notification — title and body",
      label: "Show",
      add: () =>
        toast.add({
          title: "Sweep finished",
          description:
            "Twelve runs completed in 41 minutes. The best checkpoint is a-03.",
        }),
    },
    {
      name: "Notification — still working",
      label: "Show",
      add: () =>
        toast.add({
          type: "loading",
          title: "Uploading checkpoint",
          description: "1.4 GB, about a minute left.",
          timeout: 0,
        }),
    },
    {
      name: "Notification — success, info, warning, error",
      label: "Show all four",
      add: () => {
        for (const type of ["success", "info", "warning", "error"]) {
          toast.add({
            type,
            title: `A ${type} notification`,
            description:
              "What the icon column looks like with something in it.",
          });
        }
      },
    },
    {
      name: "Notification — with an action",
      label: "Show",
      add: () =>
        toast.add({
          title: "Layout reset",
          description: "Every pane went back to where the app put it.",
          actionProps: { children: "Undo" },
        }),
    },
    {
      name: "Finished download, offered as a link",
      label: "Show",
      add: () =>
        toast.add({
          title: "frame-0042.png",
          description: (
            <a
              href={sampleImageDataUrl(LANDSCAPE)}
              download="frame-0042.png"
              className="font-medium underline underline-offset-4"
            >
              Save file
            </a>
          ),
          timeout: 0,
        }),
    },
    {
      name: "Notification the user cannot dismiss",
      label: "Show",
      add: () =>
        toast.add({
          title: "Held open by the server",
          description: "No close button: `with_close_button=False`.",
          timeout: 0,
          data: { closeButton: false },
        }),
    },
    {
      name: "A stack of them",
      label: "Show five",
      add: () => {
        for (let i = 1; i <= 5; i += 1) {
          toast.add({
            title: `Run ${i} of 5 finished`,
            description:
              "Stacked toasts collapse until the pointer is over them.",
            timeout: 0,
          });
        }
      },
    },
  ];
  return (
    <>
      {rows.map((row) => (
        <Specimen
          key={row.name}
          name={row.name}
          source="components/ui/toast.tsx"
        >
          <Button variant="outline" onClick={row.add}>
            {row.label}
          </Button>
        </Specimen>
      ))}
    </>
  );
}

/** The side drawer the kit ships and the app does not use, on each of its four
 * sides. Here so a styling pass can see what it is inheriting. */
function SheetSpecimen({
  side,
}: {
  side: "top" | "right" | "bottom" | "left";
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        Open {side}
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side={side}>
          <SheetHeader>
            <SheetTitle>Sheet from the {side}</SheetTitle>
            <SheetDescription>
              A dialog that arrives from an edge rather than the middle.
            </SheetDescription>
          </SheetHeader>
          <div className="flex flex-col gap-2 px-4">
            <SampleGuiRows prefix={`sheet-${side}`} />
          </div>
          <SheetFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Close
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* The page                                                                   */
/* -------------------------------------------------------------------------- */

function Gallery() {
  const [scheme, setScheme] = useScheme();
  return (
    <TooltipProvider>
      {/* The gallery scrolls INSIDE itself. The app's own reset stops the page
          scrolling at all -- panels and panes each scroll within their bounds
          -- and this page is loading that reset to be styled by it. */}
      <div className="h-full overflow-y-auto bg-background text-foreground">
        <header className="sticky top-0 z-10 border-b border-border bg-background">
          <div className="mx-auto flex max-w-3xl items-center gap-4 px-6 py-4">
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <h1 className="cn-font-heading text-base leading-none font-medium">
                Popup gallery
              </h1>
              <p className="text-sm text-muted-foreground">
                Every overlay the app can put on screen, in one place.
              </p>
            </div>
            <Select
              items={SCHEME_ITEMS}
              value={scheme}
              onValueChange={(next) => next !== null && setScheme(next)}
            >
              <SelectTrigger aria-label="Color scheme" className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {SCHEME_ITEMS.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
        </header>

        <main className="mx-auto flex max-w-3xl flex-col gap-10 px-6 py-8">
          <Section
            title="Dialogs"
            blurb="Centered over a backdrop, taking the whole page's attention until they are dismissed."
          >
            <Specimen name="Modal — add_modal" source="Modal.tsx">
              <ModalSpecimen />
            </Specimen>
            <Specimen name="Modal — two at once" source="Modal.tsx">
              <StackedModalSpecimen />
            </Specimen>
            <Specimen name="Command palette" source="CommandPalette.tsx">
              <CommandPaletteSpecimen />
            </Specimen>
            <Specimen
              name="Media preview — landscape picture"
              source="components/MediaPreview.tsx"
            >
              <MediaPreviewSpecimen shape={LANDSCAPE} />
            </Specimen>
            <Specimen
              name="Media preview — portrait picture, no frame to be lost in"
              source="components/MediaPreview.tsx"
            >
              <MediaPreviewSpecimen shape={PORTRAIT} />
            </Specimen>
            <FilePreviewSpecimens />
            <Specimen
              name="Stock dialog — description and footer, unused by the app"
              source="components/ui/dialog.tsx"
            >
              <StockDialogSpecimen />
            </Specimen>
          </Section>

          <Section
            title="Popovers"
            blurb="Hung off the control that opened them, aligned to the panel's edge rather than to the trigger."
          >
            <Specimen
              name="Settings popout"
              source="ControlPanel/SettingsPane.tsx"
            >
              <SettingsPopoutSpecimen />
            </Specimen>
            <Specimen
              name="Connection popout"
              source="ControlPanel/ConnectionPane.tsx"
            >
              <ConnectionPopoutSpecimen />
            </Specimen>
            <Specimen
              name="Form popout — add_form"
              source="components/Form.tsx"
            >
              <FormPopoutSpecimen />
            </Specimen>
            <Specimen
              name="Color picker popout"
              source="components/ColorPicker.tsx"
            >
              <ColorRow
                id="demo-color"
                label="Color"
                format="rgba"
                value="rgba(59, 130, 246, 0.85)"
                onReset={null}
                onValueChange={() => undefined}
              />
            </Specimen>
          </Section>

          <Section
            title="Menus"
            blurb="Lists anchored to an input, which close as soon as something is chosen."
          >
            <Specimen name="Dropdown" source="components/ui/select.tsx">
              <SelectSpecimen />
            </Specimen>
            <Specimen
              name="Dropdown — searchable"
              source="components/ui/combobox.tsx"
            >
              <ComboboxSpecimen />
            </Specimen>
          </Section>

          <Section
            title="Tooltips"
            blurb="The smallest popup there is: a hint that follows the pointer's target and never takes focus."
          >
            <Specimen name="Hint" source="components/common.tsx">
              <HintTooltip hint="What this control does.">
                <Button variant="outline">Hover me</Button>
              </HintTooltip>
            </Specimen>
            <Specimen
              name="Hint — long enough to wrap"
              source="components/common.tsx"
            >
              <HintTooltip hint="A hint long enough that it wraps inside the popup's own maximum width rather than running off the side of the window.">
                <Button variant="outline">Hover me</Button>
              </HintTooltip>
            </Specimen>
            <Specimen name="Each side" source="components/ui/tooltip.tsx">
              <TooltipSidesSpecimen />
            </Specimen>
          </Section>

          <Section
            title="Toasts"
            blurb="Notifications, stacked in the corner. They arrive without being asked for, so they are the one popup that never has a trigger in the real app."
          >
            <ToastSpecimens />
          </Section>

          <Section
            title="In the kit, unused"
            blurb="Surfaces the vendored components ship that nothing in the app currently opens. A change to how popups look reaches them anyway."
          >
            <Specimen name="Sheet — right" source="components/ui/sheet.tsx">
              <SheetSpecimen side="right" />
            </Specimen>
            <Specimen name="Sheet — left" source="components/ui/sheet.tsx">
              <SheetSpecimen side="left" />
            </Specimen>
            <Specimen name="Sheet — bottom" source="components/ui/sheet.tsx">
              <SheetSpecimen side="bottom" />
            </Specimen>
          </Section>

          <p className="pb-6 text-xs text-muted-foreground">
            Not here: the dock&rsquo;s floating panel windows, which are a
            surface of their own rather than an overlay. They have their own
            page at <span className="font-mono">/dock_test.html</span>.
          </p>
        </main>

        {/* Placed the way the app places them: bottom LEFT, clear of a
            left-docked control panel. */}
        <Toaster
          limit={10}
          style={{
            left: "1rem",
            right: "auto",
            marginInline: 0,
            width: "min(24rem, calc(100vw - 2rem))",
          }}
        />
      </div>
    </TooltipProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <Gallery />
  </React.StrictMode>,
);
