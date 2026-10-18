import React from "react";
import { createStore, createKeyedStore } from "../store";

import {
  CommandUpdateMessage,
  GuiCloseModalMessage,
  GuiComponentMessage,
  GuiFormSubmitMessage,
  GuiModalMessage,
  GuiRemoveMessage,
  GuiTabMessage,
  GuiTabUpdateMessage,
  GuiUpdateMessage,
  Message,
  RegisterCommandMessage,
  RemoveCommandMessage,
  ThemeConfigurationMessage,
  isGuiComponentMessage,
} from "../WebsocketMessages";
import { ROOT_GUI_CONTAINER_ID } from "./guiConstants";

export interface GuiState {
  theme: ThemeConfigurationMessage;
  /** Server-provided namespace for browser-owned workspace state. */
  workspaceId: string | null;
  websocketState: "connected" | "reconnecting" | "inactive";
  /** A terminal connection error, shown in place of the connection status.
   * Routine socket losses do not set one. */
  connectionError: string | null;
  guiUuidSetFromContainerUuid: {
    [containerUuid: string]: { [uuid: string]: true } | undefined;
  };
  modals: GuiModalMessage[];
  /** Each tab group's tabs, in order. */
  tabsFromGroupUuid: { [groupUuid: string]: GuiTab[] | undefined };
  guiOrderFromUuid: { [id: string]: number };
  /** The most recent form submit, as its form's UUID and a counter that only
   * goes up. A signal rather than a state: a form's popout closes when its
   * count changes, and there is nothing to clean up when the form goes away.
   * Null until the first submit of the session. */
  lastFormSubmit: { uuid: string; count: number } | null;
  uploadsInProgress: {
    [uuid: string]: {
      transferUuid: string;
      uploadedBytes: number;
      totalBytes: number;
      filename: string;
    };
  };
  /** Registered command palette actions, keyed by UUID. */
  commands: { [uuid: string]: RegisterCommandMessage };
}

/** One tab of a tab group: the container it shows, and its label and icon. */
export type GuiTab = Pick<GuiTabMessage, "uuid" | "props">;

/** Server messages that change the GUI tree, modals or commands. */
export type GuiStateMessage =
  | GuiComponentMessage
  | GuiModalMessage
  | GuiCloseModalMessage
  | GuiRemoveMessage
  | GuiUpdateMessage
  | GuiTabMessage
  | GuiTabUpdateMessage
  | GuiFormSubmitMessage
  | RegisterCommandMessage
  | CommandUpdateMessage
  | RemoveCommandMessage;

export function isGuiStateMessage(
  message: Message,
): message is GuiStateMessage {
  switch (message.type) {
    case "GuiModalMessage":
    case "GuiCloseModalMessage":
    case "GuiRemoveMessage":
    case "GuiUpdateMessage":
    case "GuiTabMessage":
    case "GuiTabUpdateMessage":
    case "GuiFormSubmitMessage":
    case "RegisterCommandMessage":
    case "CommandUpdateMessage":
    case "RemoveCommandMessage":
      return true;
    default:
      return isGuiComponentMessage(message);
  }
}

export interface GuiActions {
  setTheme: (theme: ThemeConfigurationMessage) => void;
  /** Apply server GUI messages in order as one state transaction. */
  applyMessages: (messages: readonly GuiStateMessage[]) => void;
  /** Apply a local edit, ahead of the message that reports it to Python. */
  updateGuiProps: (id: string, updates: Record<string, unknown>) => void;
  resetGui: () => void;
  updateUploadState: (
    state: (
      | { uploadedBytes: number; totalBytes: number; filename?: never }
      | GuiState["uploadsInProgress"][string]
    ) & { componentId: string; transferUuid: string },
  ) => void;
  /** Remove only the transfer that is finishing. A late completion from a
   * cancelled upload must not erase a newer upload on the same control. */
  clearUploadState: (componentId: string, transferUuid: string) => void;
}

const cleanGuiState: GuiState = {
  theme: {
    type: "ThemeConfigurationMessage",
    control_layout: "floating",
    // Matches the server's default, so the scheme does not change under the
    // viewer when the first theme message arrives.
    theme: "auto",
  },
  workspaceId: null,
  websocketState: "inactive",
  connectionError: null,
  guiUuidSetFromContainerUuid: { [ROOT_GUI_CONTAINER_ID]: {} },
  modals: [],
  tabsFromGroupUuid: {},
  guiOrderFromUuid: {},
  lastFormSubmit: null,
  uploadsInProgress: {},
  commands: {},
};

/** Apply property and value updates to a GUI component, returning the same
 * config when nothing changed so its subscribers do not re-render. */
export function applyGuiConfigUpdate(
  config: GuiComponentMessage,
  updates: Record<string, unknown>,
): GuiComponentMessage {
  const { value, ...propUpdates } = updates;
  const props = config.props as Record<string, unknown>;
  let next = config;
  if (
    "value" in updates &&
    !Object.is((config as { value?: unknown }).value, value)
  )
    next = { ...next, value } as GuiComponentMessage;
  if (
    Object.entries(propUpdates).some(
      ([key, prop]) => !Object.is(props[key], prop),
    )
  )
    next = {
      ...next,
      props: { ...props, ...propUpdates },
    } as GuiComponentMessage;
  return next;
}

/** Image bytes arrive as views into their whole websocket frame; a retained
 * control keeps only its own bytes. Unchanged bytes keep their identity so the
 * image is not decoded again. */
function ownImageBytes(
  config: GuiComponentMessage,
  previous: GuiComponentMessage | undefined,
): GuiComponentMessage {
  if (
    config.type !== "GuiImageMessage" ||
    (previous?.type === "GuiImageMessage" &&
      config.props._data === previous.props._data)
  )
    return config;
  return {
    ...config,
    props: { ...config.props, _data: config.props._data.slice() },
  };
}

/** Create an independent GUI session without mounting a React component. */
export function createGuiState() {
  const store = createStore<GuiState>(cleanGuiState);

  // Per-component config store, keyed by UUID, so one component's update
  // re-renders one component. Tabs have their own flat lifecycle, indexed
  // here from each tab to its group.
  const configStore = createKeyedStore<GuiComponentMessage>();
  const tabOwnerFromUuid = new Map<string, string>();

  const applyMessages = (messages: readonly GuiStateMessage[]) => {
    if (messages.length === 0) return;
    const state = store.get();
    const configUpdates: Record<string, GuiComponentMessage | undefined> = {};
    const config = (uuid: string) =>
      Object.hasOwn(configUpdates, uuid)
        ? configUpdates[uuid]
        : configStore.get(uuid);
    // Copy each record only once it changes, so a frame of value updates
    // leaves the tree, order and modal snapshots (and their selectors) alone.
    const draft: Partial<GuiState> = {};
    const edit = <K extends EditableField>(key: K): GuiState[K] =>
      (draft[key] ??= { ...state[key] }) as GuiState[K];
    const copiedContainers = new Set<string>();
    const members = (containerUuid: string) => {
      const containers = edit("guiUuidSetFromContainerUuid");
      if (!copiedContainers.has(containerUuid)) {
        containers[containerUuid] = { ...containers[containerUuid] };
        copiedContainers.add(containerUuid);
      }
      return containers[containerUuid]!;
    };
    let modals: Map<string, GuiModalMessage> | undefined;
    const editModals = () =>
      (modals ??= new Map(state.modals.map((modal) => [modal.uuid, modal])));

    const setTabs = (
      groupUuid: string,
      update: (tabs: GuiTab[]) => GuiTab[],
    ) => {
      const tabs = edit("tabsFromGroupUuid");
      tabs[groupUuid] = update(tabs[groupUuid] ?? []);
    };

    // Python lists every removed descendant, tabs included, so removal needs
    // no local walk.
    const remove = (uuids: readonly string[]) => {
      for (const uuid of uuids) {
        const groupUuid = tabOwnerFromUuid.get(uuid);
        if (groupUuid !== undefined) {
          tabOwnerFromUuid.delete(uuid);
          const tabs = edit("tabsFromGroupUuid");
          // Absent when the group was removed first, in the same removal.
          tabs[groupUuid] &&= tabs[groupUuid].filter(
            (tab) => tab.uuid !== uuid,
          );
          continue;
        }
        const previous = config(uuid);
        if (previous !== undefined)
          delete members(previous.container_uuid)[uuid];
        configUpdates[uuid] = undefined;
        delete edit("guiOrderFromUuid")[uuid];
        delete edit("uploadsInProgress")[uuid];
        if (previous?.type === "GuiTabGroupMessage")
          delete edit("tabsFromGroupUuid")[uuid];
      }
    };

    for (const message of messages) {
      if (isGuiComponentMessage(message)) {
        const previous = config(message.uuid);
        const next = message;
        if (previous?.container_uuid !== next.container_uuid) {
          if (previous !== undefined)
            delete members(previous.container_uuid)[next.uuid];
          members(next.container_uuid)[next.uuid] = true;
        }
        edit("guiOrderFromUuid")[next.uuid] = next.props.order;
        configUpdates[next.uuid] = ownImageBytes(next, previous);
        continue;
      }
      switch (message.type) {
        case "GuiUpdateMessage": {
          const current = config(message.uuid);
          if (current === undefined) break;
          configUpdates[message.uuid] = ownImageBytes(
            applyGuiConfigUpdate(current, message.updates),
            current,
          );
          if (typeof message.updates.order === "number")
            edit("guiOrderFromUuid")[message.uuid] = message.updates.order;
          break;
        }
        case "GuiRemoveMessage":
          remove([...message.removed_uuids, message.uuid]);
          break;
        case "GuiTabMessage":
        case "GuiTabUpdateMessage": {
          const tab = { uuid: message.uuid, props: message.props };
          tabOwnerFromUuid.set(message.uuid, message.group_uuid);
          setTabs(message.group_uuid, (current) =>
            current.some((other) => other.uuid === message.uuid)
              ? current.map((other) =>
                  other.uuid === message.uuid ? tab : other,
                )
              : [...current, tab],
          );
          break;
        }
        case "GuiModalMessage":
          editModals().set(message.uuid, message);
          break;
        case "GuiCloseModalMessage":
          editModals().delete(message.uuid);
          remove(message.removed_uuids);
          break;
        case "GuiFormSubmitMessage": {
          const previous = draft.lastFormSubmit ?? state.lastFormSubmit;
          draft.lastFormSubmit = {
            uuid: message.uuid,
            count: (previous?.count ?? 0) + 1,
          };
          break;
        }
        case "RegisterCommandMessage":
          edit("commands")[message.uuid] = message;
          break;
        case "CommandUpdateMessage": {
          const command = edit("commands")[message.uuid];
          if (command === undefined) break;
          edit("commands")[message.uuid] = {
            ...command,
            props: { ...command.props, ...message.updates },
          };
          break;
        }
        case "RemoveCommandMessage":
          delete edit("commands")[message.uuid];
          break;
      }
    }

    for (const containerUuid of copiedContainers) {
      const containers = draft.guiUuidSetFromContainerUuid!;
      if (
        containerUuid !== ROOT_GUI_CONTAINER_ID &&
        Object.keys(containers[containerUuid]!).length === 0
      )
        delete containers[containerUuid];
    }
    if (modals !== undefined)
      draft.modals = [...modals.values()].sort(
        (left, right) => left.order - right.order,
      );
    configStore.set(configUpdates);
    store.set(draft);
  };

  const actions: GuiActions = {
    setTheme: (theme) => store.set({ theme }),
    applyMessages,
    updateGuiProps: (uuid, updates) =>
      applyMessages([{ type: "GuiUpdateMessage", uuid, updates }]),
    resetGui: () => {
      // Keep the theme to avoid a visual flash. Every GUI owner belongs to the
      // connection and must not cross reconnects.
      store.set({
        // The persistence namespace belongs to this connection. Clear it
        // until the next WorkspaceConfigurationMessage arrives so a new
        // session cannot read or write the previous workspace's layout.
        workspaceId: cleanGuiState.workspaceId,
        guiUuidSetFromContainerUuid: cleanGuiState.guiUuidSetFromContainerUuid,
        modals: cleanGuiState.modals,
        tabsFromGroupUuid: cleanGuiState.tabsFromGroupUuid,
        guiOrderFromUuid: cleanGuiState.guiOrderFromUuid,
        lastFormSubmit: cleanGuiState.lastFormSubmit,
        uploadsInProgress: cleanGuiState.uploadsInProgress,
        commands: cleanGuiState.commands,
      });
      tabOwnerFromUuid.clear();
      configStore.clear();
    },
    updateUploadState: (uploadState) => {
      const state = store.get();
      const { componentId, transferUuid } = uploadState;
      const current = state.uploadsInProgress[componentId];
      // A new selection supersedes the previous one immediately. By
      // contrast, an ACK from a superseded transfer cannot recreate or
      // overwrite the progress belonging to the current selection.
      if (uploadState.filename !== undefined) {
        store.set({
          uploadsInProgress: {
            ...state.uploadsInProgress,
            [componentId]: {
              transferUuid,
              uploadedBytes: uploadState.uploadedBytes,
              totalBytes: uploadState.totalBytes,
              filename: uploadState.filename,
            },
          },
        });
        return;
      }
      if (current === undefined || current.transferUuid !== transferUuid)
        return;
      store.set({
        uploadsInProgress: {
          ...state.uploadsInProgress,
          [componentId]: {
            ...current,
            uploadedBytes: uploadState.uploadedBytes,
            totalBytes: uploadState.totalBytes,
          },
        },
      });
    },
    clearUploadState: (componentId, transferUuid) => {
      const state = store.get();
      if (state.uploadsInProgress[componentId]?.transferUuid !== transferUuid)
        return;
      const uploadsInProgress = { ...state.uploadsInProgress };
      delete uploadsInProgress[componentId];
      store.set({ uploadsInProgress });
    },
  };

  return { store, configStore, actions };
}

type EditableField =
  | "guiUuidSetFromContainerUuid"
  | "tabsFromGroupUuid"
  | "guiOrderFromUuid"
  | "uploadsInProgress"
  | "commands";

/** Own one GUI session for the lifetime of the mounted viewer. */
export function useGuiState(): GuiSession {
  return React.useState(createGuiState)[0];
}

export type GuiSession = ReturnType<typeof createGuiState>;
