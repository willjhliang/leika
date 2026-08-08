import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "./components/ui/command";
import Fuse, { FuseResult, IFuseOptions } from "fuse.js";
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useViewer } from "./ViewerContext";
import {
  commandPalette,
  useCommandPaletteOpen,
} from "./CommandPaletteController";
import { RegisterCommandMessage } from "./WebsocketMessages";
import {
  commandPaletteHotkeys,
  hotkeyMatches,
  HotkeyBinding,
} from "./commandHotkeys";
import { KeyModifier } from "./dragUtils";
import { isFormElement } from "./utils/isFormElement";
import { isMac } from "./utils/platform";

type CommandAction = {
  id: string;
  label: string;
  /** Display form of the command's hotkey, if it has one. */
  shortcut?: string;
  disabled?: boolean;
  onClick?: () => void;
  iconHtml?: string;
  keywords?: string[];
};
type HotkeyKey = NonNullable<RegisterCommandMessage["props"]["hotkey"]>;

/** Atomic modifier + key parts for a hotkey, ordered for "+"-joining. */
function hotkeyParts(key: HotkeyKey, modifier: KeyModifier | null): string[] {
  return modifier ? [...modifier.split("+"), key] : [key];
}

/** Convert a hotkey to normalized hotkey strings (e.g. "ctrl+shift+R").
 *
 * ``"cmd/ctrl"`` is OR semantics (either Ctrl or Meta counts), so we emit
 * *both* a ``"ctrl+..."`` and ``"meta+..."`` variant -- on any platform,
 * pressing either modifier triggers the hotkey. */
function hotkeyToStrings(
  key: HotkeyKey,
  modifier: KeyModifier | null,
): string[] {
  const parts = hotkeyParts(key, modifier);
  if (!parts.includes("cmd/ctrl")) {
    return [parts.join("+")];
  }
  return [
    parts.map((p) => (p === "cmd/ctrl" ? "ctrl" : p)).join("+"),
    parts.map((p) => (p === "cmd/ctrl" ? "meta" : p)).join("+"),
  ];
}

/** Format a hotkey for display (e.g. "R" + "cmd/ctrl+shift" -> "Cmd+Shift+R" or "Ctrl+Shift+R"). */
function formatHotkey(key: HotkeyKey, modifier: KeyModifier | null): string {
  return hotkeyParts(key, modifier)
    .map((part) => {
      const lower = part.toLowerCase();
      if (lower === "cmd/ctrl") return isMac ? "⌘" : "Ctrl+";
      if (lower === "shift") return isMac ? "⇧" : "Shift+";
      if (lower === "alt") return isMac ? "⌥" : "Alt+";
      return part;
    })
    .join("");
}

/** Build searchable entries from the registered command map. */
function useCommandActions(
  commands: Record<string, RegisterCommandMessage>,
  onTrigger: (uuid: string) => void,
): CommandAction[] {
  return useMemo(
    () =>
      Object.values(commands).map((command) => {
        const hotkey = command.props.hotkey;
        const disabled = command.props.disabled;
        return {
          id: command.uuid,
          label: command.props.label,
          // The hotkey rides in its own slot rather than being appended to the
          // label, which is what CommandShortcut is for.
          shortcut: hotkey
            ? formatHotkey(hotkey, command.props.modifier)
            : undefined,
          disabled,
          onClick: disabled ? undefined : () => onTrigger(command.uuid),
          iconHtml: command.props._icon_html ?? undefined,
          // Descriptions are no longer shown, but they stay searchable.
          keywords: command.props.description
            ? [command.props.description]
            : undefined,
        };
      }),
    [commands, onTrigger],
  );
}

const FUSE_OPTIONS: IFuseOptions<CommandAction> = {
  keys: ["label", "keywords"],
  threshold: 0.4,
  ignoreLocation: true,
};

/** Hook returning a stable fuzzy filter function that reuses its Fuse index. */
function useFuseFilter() {
  const fuseRef = useRef<{
    items: CommandAction[];
    fuse: Fuse<CommandAction>;
  } | null>(null);

  return useCallback((query: string, items: CommandAction[]) => {
    const normalizedQuery = query.trim();
    if (!normalizedQuery) return items;

    // Rebuild the Fuse index only when the registered command list changes.
    if (!fuseRef.current || fuseRef.current.items !== items) {
      fuseRef.current = { items, fuse: new Fuse(items, FUSE_OPTIONS) };
    }
    return fuseRef.current.fuse
      .search(normalizedQuery)
      .map((result: FuseResult<CommandAction>) => result.item);
  }, []);
}

export function CommandPalette() {
  const viewer = useViewer();
  const commands = viewer.useGui((state) => state.commands);
  const viewerMutable = viewer.mutable.current;
  const opened = useCommandPaletteOpen();
  const [query, setQuery] = useState("");
  const [highlightedId, setHighlightedId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleTrigger = useCallback(
    (uuid: string) => {
      viewerMutable.sendMessage({
        type: "CommandTriggerMessage",
        uuid,
      });
    },
    [viewerMutable],
  );

  const actions = useCommandActions(commands, handleTrigger);
  const fuseFilter = useFuseFilter();
  const visibleActions = useMemo(
    () => fuseFilter(query, actions),
    [actions, fuseFilter, query],
  );
  const selectableActions = useMemo(
    () => visibleActions.filter((action) => !action.disabled),
    [visibleActions],
  );
  const wasOpenedRef = useRef(false);

  useEffect(() => {
    const justOpened = opened && !wasOpenedRef.current;
    wasOpenedRef.current = opened;
    if (!justOpened) return;
    setQuery("");
    setHighlightedId(actions.find((action) => !action.disabled)?.id ?? null);
    const frame = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [actions, opened]);

  useEffect(() => {
    if (
      highlightedId === null ||
      !selectableActions.some((action) => action.id === highlightedId)
    ) {
      setHighlightedId(selectableActions[0]?.id ?? null);
    }
  }, [highlightedId, selectableActions]);

  useEffect(() => {
    if (actions.length === 0 && opened) commandPalette.close();
  }, [actions.length, opened]);

  // Each registered hotkey may expand to Ctrl and Meta variants. Palette
  // shortcuts share the same hook so teardown remains atomic when commands
  // change.
  const hotkeyItems = useMemo(() => {
    const openPalette = () => commandPalette.open();
    const commandHotkeys = Object.values(commands)
      .filter(
        (command) => command.props.hotkey != null && !command.props.disabled,
      )
      .flatMap((command) => {
        const trigger = () => handleTrigger(command.uuid);
        return hotkeyToStrings(
          command.props.hotkey!,
          command.props.modifier,
        ).map((key) => [key, trigger] as [string, typeof trigger]);
      });
    return commandPaletteHotkeys(
      Object.keys(commands).length > 0,
      openPalette,
      commandHotkeys,
    );
  }, [commands, handleTrigger]);
  useHotkeys(hotkeyItems);

  const triggerAction = (action: CommandAction) => {
    if (action.disabled || action.onClick === undefined) return;
    commandPalette.close();
    action.onClick();
  };

  if (actions.length === 0) return null;

  return (
    <CommandDialog
      open={opened}
      onOpenChange={(open) => {
        if (!open) commandPalette.close();
      }}
      title="Commands"
      description="Search for a registered Leika command."
    >
      <Command
        data-leika-command-palette
        label="Search commands"
        shouldFilter={false}
        value={highlightedId ?? ""}
        onValueChange={setHighlightedId}
      >
        <CommandInput
          ref={inputRef}
          aria-label="Search commands"
          aria-controls="leika-command-list"
          value={query}
          placeholder="Search commands..."
          onValueChange={setQuery}
        />
        <CommandList id="leika-command-list" data-leika-command-list>
          <CommandEmpty>No matching commands...</CommandEmpty>
          {/* Every command sits in one group: the group is what insets the
              items from the popup's edges, so it is structural rather than
              decorative even with a single flat list. Its heading is what puts
              air between the search box and the first row -- the box and the
              group otherwise contribute 4px between them -- and it is the same
              heading a multi-group palette would use, so one list and many
              read alike. */}
          <CommandGroup heading="Commands">
            {visibleActions.map((action) => (
              <CommandItem
                key={action.id}
                id={"leika-command-" + action.id}
                value={action.id}
                keywords={action.keywords}
                data-leika-command-action
                disabled={action.disabled}
                onMouseMove={() => {
                  if (!action.disabled) setHighlightedId(action.id);
                }}
                onSelect={() => triggerAction(action)}
              >
                {action.iconHtml ? (
                  <span
                    aria-hidden="true"
                    className="flex items-center"
                    dangerouslySetInnerHTML={{ __html: action.iconHtml }}
                  />
                ) : null}
                <span className="min-w-0 flex-1 truncate">{action.label}</span>
                {action.shortcut ? (
                  <CommandShortcut>{action.shortcut}</CommandShortcut>
                ) : null}
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </Command>
    </CommandDialog>
  );
}

/** Bind window-level hotkeys, ignoring keystrokes typed into form fields. */
function useHotkeys(hotkeys: readonly HotkeyBinding[]) {
  const handlers = useRef(hotkeys);
  handlers.current = hotkeys;
  const enabled = hotkeys.length > 0;
  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (isFormElement(event.target)) return;
      const match = handlers.current.find(([definition]) =>
        hotkeyMatches(event, definition),
      );
      if (match === undefined) return;
      event.preventDefault();
      match[1]();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled]);
}
