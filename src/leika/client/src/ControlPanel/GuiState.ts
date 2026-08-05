import React from "react";
import { createStore, createKeyedStore } from "../store";

import {
  GuiComponentMessage,
  GuiModalMessage,
  RegisterCommandMessage,
  ThemeConfigurationMessage,
} from "../WebsocketMessages";

export interface GuiState {
  theme: ThemeConfigurationMessage;
  label: string;
  server: string;
  websocketState: "connected" | "reconnecting" | "inactive";
  /** Fatal reason the server refused this client (e.g. a version mismatch),
   * shown in place of the connection status. Null whenever the connection is
   * merely down and retrying. */
  connectionError: string | null;
  guiUuidSetFromContainerUuid: {
    [containerUuid: string]: { [uuid: string]: true } | undefined;
  };
  modals: GuiModalMessage[];
  guiOrderFromUuid: { [id: string]: number };
  /** The most recent form submit, as its form's UUID and a counter that only
   * goes up. A signal rather than a state: a form's popout closes when its
   * count changes, and there is nothing to clean up when the form goes away.
   * Null until the first submit of the session. */
  lastFormSubmit: { uuid: string; count: number } | null;
  uploadsInProgress: {
    [uuid: string]: {
      uploadedBytes: number;
      totalBytes: number;
      filename: string;
    };
  };
  /** Registered command palette actions, keyed by UUID. */
  commands: { [uuid: string]: RegisterCommandMessage };
}

export interface GuiActions {
  setTheme: (theme: ThemeConfigurationMessage) => void;
  addGui: (config: GuiComponentMessage) => void;
  addModal: (config: GuiModalMessage) => void;
  removeModal: (id: string) => void;
  updateGuiProps: (id: string, updates: Record<string, unknown>) => void;
  /** Record that a form was submitted, whoever submitted it. */
  noteFormSubmit: (uuid: string) => void;
  /** Move components within their containers.
   *
   * Ordering lives in a map of its own -- containers sort on it, while the
   * per-component configs sit in a separate store so that one component's
   * update re-renders one component. An `order` that arrives after the
   * component was created therefore has to be written HERE as well, or the
   * element keeps the place it was created in: this is how a form's submit
   * button reaches the bottom of the form it was created at the top of. */
  reorderGui: (orderFromUuid: { [uuid: string]: number }) => void;
  removeGui: (id: string) => void;
  resetGui: () => void;
  updateUploadState: (
    state: (
      | { uploadedBytes: number; totalBytes: number }
      | GuiState["uploadsInProgress"][string]
    ) & { componentId: string },
  ) => void;
  addCommand: (command: RegisterCommandMessage) => void;
  updateCommand: (uuid: string, updates: Record<string, unknown>) => void;
  removeCommand: (uuid: string) => void;
}

const cleanGuiState: GuiState = {
  theme: {
    type: "ThemeConfigurationMessage",
    control_layout: "floating",
    // Matches the server's default, so the scheme does not change under the
    // viewer when the first theme message arrives.
    dark_mode: "auto",
  },
  label: "",
  server: "",
  websocketState: "inactive",
  connectionError: null,
  guiUuidSetFromContainerUuid: { root: {} },
  modals: [],
  guiOrderFromUuid: {},
  lastFormSubmit: null,
  uploadsInProgress: {},
  commands: {},
};

/**
 * Apply property updates to a GUI component.
 * Returns a new config with the updates applied, or the same config
 * reference if nothing actually changed.
 */
export function applyGuiConfigUpdate(
  config: GuiComponentMessage,
  updates: Record<string, unknown>,
): GuiComponentMessage {
  let propsChanged = false;
  let valueChanged = false;

  for (const [key, value] of Object.entries(updates)) {
    if (key === "value") {
      const current = "value" in config ? config.value : undefined;
      if (!Object.is(current, value)) valueChanged = true;
    } else if (!(key in config.props)) {
      console.error(
        `Tried to update nonexistent property '${key}' of GUI element!`,
      );
    } else {
      if (!Object.is((config.props as Record<string, unknown>)[key], value))
        propsChanged = true;
    }
  }

  if (!propsChanged && !valueChanged) return config;

  let newConfig = config;
  if (valueChanged) {
    newConfig = { ...newConfig, value: updates.value } as GuiComponentMessage;
  }
  if (propsChanged) {
    const newProps = { ...config.props } as Record<string, unknown>;
    for (const [key, value] of Object.entries(updates)) {
      if (key !== "value" && key in config.props) {
        newProps[key] = value;
      }
    }
    newConfig = { ...newConfig, props: newProps } as GuiComponentMessage;
  }

  return newConfig;
}

export function useGuiState(initialServer: string) {
  return React.useState(() => {
    const store = createStore<GuiState>({
      ...cleanGuiState,
      server: initialServer,
    });

    // Per-component config store, keyed by UUID.
    const configStore = createKeyedStore<GuiComponentMessage>();

    const actions: GuiActions = {
      setTheme: (theme) => store.set({ theme }),
      addGui: (guiConfig) => {
        const state = store.get();
        const containerSet =
          state.guiUuidSetFromContainerUuid[guiConfig.container_uuid] ?? {};
        store.set({
          guiOrderFromUuid: {
            ...state.guiOrderFromUuid,
            [guiConfig.uuid]: guiConfig.props.order,
          },
          guiUuidSetFromContainerUuid: {
            ...state.guiUuidSetFromContainerUuid,
            [guiConfig.container_uuid]: {
              ...containerSet,
              [guiConfig.uuid]: true as const,
            },
          },
        });
        configStore.set({ [guiConfig.uuid]: guiConfig });
      },
      addModal: (modalConfig) => {
        store.set((state) => ({
          modals: [...state.modals, modalConfig].sort(
            (left, right) => left.order - right.order,
          ),
        }));
      },
      removeModal: (id) => {
        store.set((state) => ({
          modals: state.modals.filter((m) => m.uuid !== id),
        }));
      },
      removeGui: (id) => {
        const guiConfig = configStore.get(id);
        if (guiConfig === undefined) return;
        const state = store.get();
        const remainingOrders = { ...state.guiOrderFromUuid };
        delete remainingOrders[id];
        const containerUuid = guiConfig.container_uuid;
        const containerSet = {
          ...state.guiUuidSetFromContainerUuid[containerUuid],
        };
        delete containerSet[id];
        const newContainerMap = {
          ...state.guiUuidSetFromContainerUuid,
        };
        if (Object.keys(containerSet).length === 0) {
          delete newContainerMap[containerUuid];
        } else {
          newContainerMap[containerUuid] = containerSet;
        }
        store.set({
          guiOrderFromUuid: remainingOrders,
          guiUuidSetFromContainerUuid: newContainerMap,
        });
        configStore.set({ [id]: undefined });
      },
      resetGui: () => {
        // No need to overwrite the theme or label. The former especially
        // can be jarring.
        store.set({
          guiUuidSetFromContainerUuid:
            cleanGuiState.guiUuidSetFromContainerUuid,
          modals: cleanGuiState.modals,
          guiOrderFromUuid: cleanGuiState.guiOrderFromUuid,
          lastFormSubmit: cleanGuiState.lastFormSubmit,
          uploadsInProgress: cleanGuiState.uploadsInProgress,
          commands: cleanGuiState.commands,
        });
        configStore.setAll({}, true);
      },
      updateUploadState: (uploadState) => {
        const state = store.get();
        const { componentId, ...rest } = uploadState;
        store.set({
          uploadsInProgress: {
            ...state.uploadsInProgress,
            [componentId]: {
              ...state.uploadsInProgress[componentId],
              ...rest,
            },
          },
        });
      },
      addCommand: (command) => {
        store.set((state) => {
          // Skip if an identical command is already registered (e.g. server
          // reconnect replaying RegisterCommandMessage for every existing
          // command). Prevents churning the whole subscriber set.
          if (Object.is(state.commands[command.uuid], command)) return state;
          return { commands: { ...state.commands, [command.uuid]: command } };
        });
      },
      updateCommand: (uuid, updates) => {
        store.set((state) => {
          const existing = state.commands[uuid];
          if (existing === undefined) return state;
          const existingProps = existing.props as Record<string, unknown>;
          const changed = Object.entries(updates).some(
            ([k, v]) => !Object.is(existingProps[k], v),
          );
          if (!changed) return state;
          const merged: RegisterCommandMessage = {
            ...existing,
            props: { ...existing.props, ...updates },
          };
          return { commands: { ...state.commands, [uuid]: merged } };
        });
      },
      removeCommand: (uuid) => {
        store.set((state) => {
          if (!(uuid in state.commands)) return state;
          const next = { ...state.commands };
          delete next[uuid];
          return { commands: next };
        });
      },
      updateGuiProps: (id, updates) => {
        const config = configStore.get(id);
        if (config === undefined) {
          console.error(
            `Tried to update non-existent component '${id}' with`,
            updates,
          );
          return;
        }
        const newConfig = applyGuiConfigUpdate(config, updates);
        if (newConfig !== config) {
          configStore.set({ [id]: newConfig });
        }
      },
      noteFormSubmit: (uuid) => {
        store.set((state) => ({
          lastFormSubmit: {
            uuid,
            count: (state.lastFormSubmit?.count ?? 0) + 1,
          },
        }));
      },
      reorderGui: (orderFromUuid) => {
        store.set((state) => {
          const changed = Object.entries(orderFromUuid).filter(
            ([uuid, order]) => state.guiOrderFromUuid[uuid] !== order,
          );
          if (changed.length === 0) return state;
          return {
            guiOrderFromUuid: {
              ...state.guiOrderFromUuid,
              ...Object.fromEntries(changed),
            },
          };
        });
      },
    };

    return { store, configStore, actions };
  })[0];
}

/** Type corresponding to the useGuiState hook return. */
export type UseGui = ReturnType<typeof useGuiState>;
