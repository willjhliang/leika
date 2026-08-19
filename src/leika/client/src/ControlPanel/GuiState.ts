import React from "react";
import { createStore, createKeyedStore } from "../store";
import { cloneRecord, emptyRecord } from "../recordUtils";
import {
  MAX_BROWSER_LIVE_GUI_COMMANDS,
  MAX_BROWSER_LIVE_GUI_COMPONENTS,
  MAX_BROWSER_LIVE_GUI_MODALS,
  addGuiConfigCosts,
  guiConfigCost,
  guiConfigCostWithinBrowserLimits,
  guiConfigWithinEntityLimits,
  guiCommandWithinEntityLimits,
  guiCommandCost,
  guiModalWithinEntityLimits,
  guiModalCost,
  subtractGuiConfigCosts,
  type GuiConfigCost,
} from "../guiLimits";

import {
  GuiComponentMessage,
  GuiModalMessage,
  GuiTabMessage,
  GuiTabUpdateMessage,
  Message,
  RegisterCommandMessage,
  ThemeConfigurationMessage,
  isGuiComponentMessage,
  validateMessage,
} from "../WebsocketMessages";
import { ROOT_GUI_CONTAINER_ID } from "./guiConstants";
import { isBoundedLayoutId } from "../persistenceLimits";
import {
  createGuiProjection,
  effectiveGuiCreate,
  guiContainerGraphIsValid,
  projectGuiRemoval,
  projectGuiTabLifecycle,
  setProjectedGuiConfig,
  type GuiTabLifecycleMessage,
} from "./guiLifecycleProjection";

export interface GuiState {
  theme: ThemeConfigurationMessage;
  server: string;
  /** Server-provided namespace for browser-owned workspace state. */
  workspaceId: string | null;
  websocketState: "connected" | "reconnecting" | "inactive";
  /** A terminal connection error or a retryable local-safety diagnostic,
   * shown in place of the connection status. Routine socket losses do not set
   * one; a successful connection clears any diagnostic left by a retry. */
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
      transferUuid: string;
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
  addGuiBatch: (configs: readonly GuiComponentMessage[]) => void;
  addModal: (config: GuiModalMessage) => void;
  addModalBatch: (configs: readonly GuiModalMessage[]) => void;
  applyTabLifecycleBatch: (messages: readonly GuiTabLifecycleMessage[]) => void;
  declareTab: (message: GuiTabMessage) => void;
  updateTab: (message: GuiTabUpdateMessage) => void;
  removeModal: (
    id: string,
    removedUuids?: readonly string[],
    removedTabUuids?: readonly string[],
  ) => void;
  updateGuiProps: (id: string, updates: Record<string, unknown>) => void;
  updateGuiPropsBatch: (
    updates: ReadonlyMap<string, Record<string, unknown>>,
  ) => void;
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
  removeGui: (
    id: string,
    removedUuids?: readonly string[],
    removedTabUuids?: readonly string[],
  ) => void;
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
  addCommand: (command: RegisterCommandMessage) => void;
  addCommandBatch: (commands: readonly RegisterCommandMessage[]) => void;
  /** Pure trust-boundary admission for one original websocket frame. */
  preflightMessageBatch: (messages: readonly Message[]) => string | null;
  updateCommand: (uuid: string, updates: Record<string, unknown>) => void;
  removeCommand: (uuid: string) => void;
}

const rootGuiContainers = emptyRecord<{ [uuid: string]: true } | undefined>();
rootGuiContainers[ROOT_GUI_CONTAINER_ID] = emptyRecord<true>();

const cleanGuiState: GuiState = {
  theme: {
    type: "ThemeConfigurationMessage",
    control_layout: "floating",
    // Matches the server's default, so the scheme does not change under the
    // viewer when the first theme message arrives.
    dark_mode: "auto",
  },
  server: "",
  workspaceId: null,
  websocketState: "inactive",
  connectionError: null,
  guiUuidSetFromContainerUuid: rootGuiContainers,
  modals: [],
  guiOrderFromUuid: emptyRecord<number>(),
  lastFormSubmit: null,
  uploadsInProgress: emptyRecord(),
  commands: emptyRecord(),
};

/**
 * Apply property updates to a GUI component.
 * Returns a new config with the updates applied, or the same config
 * reference if nothing actually changed.
 */
function buildGuiConfigUpdate(
  config: GuiComponentMessage,
  updates: Record<string, unknown>,
): GuiComponentMessage {
  let propsChanged = false;
  let valueChanged = false;

  for (const [key, value] of Object.entries(updates)) {
    if (key === "value") {
      const current = "value" in config ? config.value : undefined;
      if (!Object.is(current, value)) valueChanged = true;
    } else if (!Object.hasOwn(config.props, key)) {
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
      if (key !== "value" && Object.hasOwn(config.props, key)) {
        Object.defineProperty(newProps, key, {
          configurable: true,
          enumerable: true,
          value,
          writable: true,
        });
      }
    }
    newConfig = { ...newConfig, props: newProps } as GuiComponentMessage;
  }

  return newConfig;
}

function validUpdatedGuiConfig(
  config: GuiComponentMessage,
  updates: Record<string, unknown>,
): GuiComponentMessage | null {
  if (config.type === "GuiTabGroupMessage" && Object.hasOwn(updates, "_tabs")) {
    return null;
  }
  const candidate = buildGuiConfigUpdate(config, updates);
  try {
    validateMessage(candidate);
  } catch {
    return null;
  }
  return guiConfigWithinEntityLimits(candidate) ? candidate : null;
}

export function applyGuiConfigUpdate(
  config: GuiComponentMessage,
  updates: Record<string, unknown>,
): GuiComponentMessage {
  const newConfig = validUpdatedGuiConfig(config, updates);
  if (newConfig === null) {
    console.error("Rejected GUI update that exceeds browser safety limits.");
    return config;
  }
  return newConfig;
}

function removalDescendants(message: Message): readonly string[] {
  return message.type === "GuiRemoveMessage" ||
    message.type === "GuiCloseModalMessage"
    ? message.removed_uuids
    : [];
}

function removalTabs(message: Message): readonly string[] {
  return message.type === "GuiRemoveMessage" ||
    message.type === "GuiCloseModalMessage"
    ? message.removed_tab_uuids
    : [];
}

const MAX_GUI_CONTAINER_DEPTH = 64;
const MAX_GUI_REMOVAL_TOMBSTONES = 4_096;
const MAX_GUI_TAB_REMOVAL_TOMBSTONES = 16_384;

function removalTombstonesAreValid(message: Message): boolean {
  const descendants = removalDescendants(message);
  const tabs = removalTabs(message);
  if (
    descendants.length > MAX_GUI_REMOVAL_TOMBSTONES ||
    tabs.length > MAX_GUI_TAB_REMOVAL_TOMBSTONES
  ) {
    return false;
  }
  const primary =
    "uuid" in message && typeof message.uuid === "string" ? message.uuid : null;
  if (primary === null || !isBoundedLayoutId(primary)) return false;
  const componentUuids = new Set<string>();
  for (const uuid of descendants) {
    if (
      !isBoundedLayoutId(uuid) ||
      uuid === primary ||
      componentUuids.has(uuid)
    ) {
      return false;
    }
    componentUuids.add(uuid);
  }
  const tabUuids = new Set<string>();
  for (const uuid of tabs) {
    if (
      !isBoundedLayoutId(uuid) ||
      uuid === primary ||
      componentUuids.has(uuid) ||
      tabUuids.has(uuid)
    ) {
      return false;
    }
    tabUuids.add(uuid);
  }
  return true;
}

function detachGuiConfigBinary(
  config: GuiComponentMessage,
): GuiComponentMessage {
  if (config.type !== "GuiImageMessage") return config;
  return {
    ...config,
    props: { ...config.props, _data: config.props._data.slice() },
  };
}

export function useGuiState(initialServer: string) {
  return React.useState(() => {
    const store = createStore<GuiState>({
      ...cleanGuiState,
      server: initialServer,
    });

    // Per-component config store, keyed by UUID. Tab lifecycle owners are
    // retained separately; each group's derived tab array is the sole
    // rendering snapshot and participates in the aggregate resource ledger.
    const configStore = createKeyedStore<GuiComponentMessage>();
    const tabOwnerFromUuid = new Map<string, string>();
    let aggregateGuiCost: GuiConfigCost = {
      collectionItems: 0,
      retainedBytes: 0,
      textCodeUnits: 0,
    };

    const addGuiBatch = (guiConfigs: readonly GuiComponentMessage[]) => {
      if (guiConfigs.length === 0) return;
      const failure = preflightMessageBatch(guiConfigs);
      if (failure !== null) {
        console.error(failure);
        return;
      }
      const state = store.get();
      const containerMap = cloneRecord(state.guiUuidSetFromContainerUuid);
      const mutableContainers = new Set<string>();
      const touchedContainers = new Set<string>();
      const guiOrderFromUuid = cloneRecord(state.guiOrderFromUuid);
      const configUpdates = emptyRecord<GuiComponentMessage | undefined>();
      let nextCost = aggregateGuiCost;
      let liveCount = configStore.size();

      const membersForWrite = (containerUuid: string) => {
        if (!mutableContainers.has(containerUuid)) {
          containerMap[containerUuid] = cloneRecord(
            containerMap[containerUuid] ?? emptyRecord<true>(),
          );
          mutableContainers.add(containerUuid);
        }
        touchedContainers.add(containerUuid);
        return containerMap[containerUuid]!;
      };

      for (const incoming of guiConfigs) {
        const previous = Object.hasOwn(configUpdates, incoming.uuid)
          ? configUpdates[incoming.uuid]
          : configStore.get(incoming.uuid);
        const guiConfig = effectiveGuiCreate(incoming, previous);
        if (guiConfig === null) {
          throw new Error("GUI create preflight/commit invariant failed");
        }
        const previousCost =
          previous === undefined
            ? { collectionItems: 0, retainedBytes: 0, textCodeUnits: 0 }
            : guiConfigCost(previous);
        const candidateCost = addGuiConfigCosts(
          subtractGuiConfigCosts(nextCost, previousCost),
          guiConfigCost(guiConfig),
        );
        if (
          !guiConfigWithinEntityLimits(guiConfig) ||
          (previous === undefined &&
            liveCount >= MAX_BROWSER_LIVE_GUI_COMPONENTS) ||
          !guiConfigCostWithinBrowserLimits(candidateCost)
        ) {
          throw new Error("GUI preflight/commit invariant failed");
        }
        if (previous === undefined) liveCount += 1;
        if (
          previous !== undefined &&
          previous.container_uuid !== guiConfig.container_uuid
        ) {
          delete membersForWrite(previous.container_uuid)[guiConfig.uuid];
        }
        membersForWrite(guiConfig.container_uuid)[guiConfig.uuid] = true;
        guiOrderFromUuid[guiConfig.uuid] = guiConfig.props.order;
        configUpdates[guiConfig.uuid] = detachGuiConfigBinary(guiConfig);
        nextCost = candidateCost;
      }
      for (const containerUuid of touchedContainers) {
        if (Object.keys(containerMap[containerUuid]!).length === 0) {
          delete containerMap[containerUuid];
        }
      }
      configStore.set(configUpdates);
      aggregateGuiCost = nextCost;
      store.set({
        guiOrderFromUuid,
        guiUuidSetFromContainerUuid: containerMap,
      });
    };

    const addModalBatch = (modalConfigs: readonly GuiModalMessage[]) => {
      if (modalConfigs.length === 0) return;
      const failure = preflightMessageBatch(modalConfigs);
      if (failure !== null) {
        console.error(failure);
        return;
      }
      const current = new Map(
        store
          .get()
          .modals.map((modalConfig) => [modalConfig.uuid, modalConfig]),
      );
      let nextCost = aggregateGuiCost;
      for (const modalConfig of modalConfigs) {
        if (
          !guiModalWithinEntityLimits(modalConfig) ||
          (!current.has(modalConfig.uuid) &&
            current.size >= MAX_BROWSER_LIVE_GUI_MODALS)
        ) {
          throw new Error("modal preflight/commit invariant failed");
        }
        const previous = current.get(modalConfig.uuid);
        nextCost = addGuiConfigCosts(
          previous === undefined
            ? nextCost
            : subtractGuiConfigCosts(nextCost, guiModalCost(previous)),
          guiModalCost(modalConfig),
        );
        current.set(modalConfig.uuid, modalConfig);
      }
      aggregateGuiCost = nextCost;
      store.set({
        modals: [...current.values()].sort(
          (left, right) => left.order - right.order,
        ),
      });
    };

    const addCommandBatch = (
      commandConfigs: readonly RegisterCommandMessage[],
    ) => {
      if (commandConfigs.length === 0) return;
      const failure = preflightMessageBatch(commandConfigs);
      if (failure !== null) {
        console.error(failure);
        return;
      }
      const commands = cloneRecord(store.get().commands);
      let liveCount = Object.keys(commands).length;
      let changed = false;
      let nextCost = aggregateGuiCost;
      for (const command of commandConfigs) {
        const exists = Object.hasOwn(commands, command.uuid);
        if (
          !guiCommandWithinEntityLimits(command) ||
          (!exists && liveCount >= MAX_BROWSER_LIVE_GUI_COMMANDS)
        ) {
          throw new Error("command preflight/commit invariant failed");
        }
        if (Object.is(commands[command.uuid], command)) continue;
        const previous = commands[command.uuid];
        nextCost = addGuiConfigCosts(
          previous === undefined
            ? nextCost
            : subtractGuiConfigCosts(nextCost, guiCommandCost(previous)),
          guiCommandCost(command),
        );
        if (!exists) liveCount += 1;
        commands[command.uuid] = command;
        changed = true;
      }
      if (changed) {
        aggregateGuiCost = nextCost;
        store.set({ commands });
      }
    };

    const applyTabLifecycleBatch = (
      messages: readonly GuiTabLifecycleMessage[],
    ) => {
      if (messages.length === 0) return;
      const failure = preflightMessageBatch(messages);
      if (failure !== null) {
        console.error(failure);
        return;
      }
      const currentConfigs = new Map(
        configStore.values().map((config) => [config.uuid, config]),
      );
      const projection = createGuiProjection(
        currentConfigs,
        tabOwnerFromUuid,
        aggregateGuiCost,
      );
      const modals = new Map(
        store
          .get()
          .modals.map((modalConfig) => [modalConfig.uuid, modalConfig]),
      );
      for (const message of messages) {
        const detail = projectGuiTabLifecycle(projection, modals, message);
        if (detail !== null) {
          throw new Error("tab lifecycle preflight/commit invariant failed");
        }
      }
      const configUpdates = emptyRecord<GuiComponentMessage | undefined>();
      for (const [uuid, config] of projection.configs) {
        if (!Object.is(currentConfigs.get(uuid), config)) {
          configUpdates[uuid] = config;
        }
      }
      if (Object.keys(configUpdates).length > 0) {
        configStore.set(configUpdates);
      }
      replaceTabOwners(projection.tabOwnerFromUuid);
      aggregateGuiCost = projection.cost;
    };

    const replaceTabOwners = (owners: ReadonlyMap<string, string>) => {
      tabOwnerFromUuid.clear();
      for (const [tabUuid, groupUuid] of owners) {
        tabOwnerFromUuid.set(tabUuid, groupUuid);
      }
    };

    const purgeGui = (
      initialComponents: readonly string[],
      initialContainers: readonly string[],
      initialTabs: readonly string[],
      modalUuid?: string,
    ) => {
      const state = store.get();
      const currentConfigs = new Map(
        configStore.values().map((config) => [config.uuid, config]),
      );
      const projection = createGuiProjection(
        currentConfigs,
        tabOwnerFromUuid,
        aggregateGuiCost,
      );
      const { removedComponents, removedContainers } = projectGuiRemoval(
        projection,
        initialComponents,
        initialContainers,
        initialTabs,
      );

      const configUpdates = emptyRecord<GuiComponentMessage | undefined>();
      for (const [uuid, config] of currentConfigs) {
        const projected = projection.configs.get(uuid);
        if (projected === undefined) configUpdates[uuid] = undefined;
        else if (!Object.is(projected, config)) configUpdates[uuid] = projected;
      }
      if (Object.keys(configUpdates).length > 0) {
        configStore.set(configUpdates);
      }
      replaceTabOwners(projection.tabOwnerFromUuid);
      aggregateGuiCost = projection.cost;

      const guiOrderFromUuid = cloneRecord(state.guiOrderFromUuid);
      const uploadsInProgress = cloneRecord(state.uploadsInProgress);
      for (const uuid of removedComponents) {
        delete guiOrderFromUuid[uuid];
        delete uploadsInProgress[uuid];
      }

      const containerMap = cloneRecord(state.guiUuidSetFromContainerUuid);
      for (const [containerUuid, members] of Object.entries(containerMap)) {
        if (members === undefined) continue;
        if (removedContainers.has(containerUuid)) {
          delete containerMap[containerUuid];
          continue;
        }
        let nextMembers: Record<string, true> | null = null;
        for (const uuid of Object.keys(members)) {
          if (!removedComponents.has(uuid)) continue;
          nextMembers ??= cloneRecord(members);
          delete nextMembers[uuid];
        }
        if (nextMembers === null) continue;
        if (Object.keys(nextMembers).length === 0) {
          delete containerMap[containerUuid];
        } else {
          containerMap[containerUuid] = nextMembers;
        }
      }
      if (!Object.hasOwn(containerMap, ROOT_GUI_CONTAINER_ID)) {
        containerMap[ROOT_GUI_CONTAINER_ID] = emptyRecord<true>();
      }

      if (modalUuid !== undefined) {
        const removedModal = state.modals.find(
          (modal) => modal.uuid === modalUuid,
        );
        if (removedModal !== undefined) {
          aggregateGuiCost = subtractGuiConfigCosts(
            aggregateGuiCost,
            guiModalCost(removedModal),
          );
        }
      }
      store.set({
        guiOrderFromUuid,
        guiUuidSetFromContainerUuid: containerMap,
        modals:
          modalUuid === undefined
            ? state.modals
            : state.modals.filter((modal) => modal.uuid !== modalUuid),
        uploadsInProgress,
      });
    };

    const updateGuiPropsBatch = (
      updatesFromUuid: ReadonlyMap<string, Record<string, unknown>>,
    ) => {
      if (updatesFromUuid.size === 0) return;
      const messages: Message[] = [];
      for (const [uuid, updates] of updatesFromUuid) {
        messages.push({ type: "GuiUpdateMessage", uuid, updates });
      }
      const failure = preflightMessageBatch(messages);
      if (failure !== null) {
        console.error(failure);
        return;
      }
      const configUpdates = emptyRecord<GuiComponentMessage | undefined>();
      const orderUpdates = emptyRecord<number>();
      let nextCost = aggregateGuiCost;
      for (const [uuid, updates] of updatesFromUuid) {
        const current = configStore.get(uuid);
        if (current === undefined) continue;
        const updated = applyGuiConfigUpdate(current, updates);
        if (updated === current) continue;
        const candidateCost = addGuiConfigCosts(
          subtractGuiConfigCosts(nextCost, guiConfigCost(current)),
          guiConfigCost(updated),
        );
        if (!guiConfigCostWithinBrowserLimits(candidateCost)) {
          throw new Error("GUI update preflight/commit invariant failed");
        }
        configUpdates[uuid] = detachGuiConfigBinary(updated);
        if (typeof updates.order === "number") {
          orderUpdates[uuid] = updates.order;
        }
        nextCost = candidateCost;
      }
      if (Object.keys(configUpdates).length > 0) {
        configStore.set(configUpdates);
        aggregateGuiCost = nextCost;
      }
      if (Object.keys(orderUpdates).length > 0) {
        const state = store.get();
        const guiOrderFromUuid = cloneRecord(state.guiOrderFromUuid);
        for (const [uuid, order] of Object.entries(orderUpdates)) {
          guiOrderFromUuid[uuid] = order;
        }
        store.set({ guiOrderFromUuid });
      }
    };

    const preflightMessageBatch = (
      messages: readonly Message[],
    ): string | null => {
      const projection = createGuiProjection(
        configStore.values().map((config) => [config.uuid, config] as const),
        tabOwnerFromUuid,
        aggregateGuiCost,
      );
      const modals = new Map(
        store
          .get()
          .modals.map((modalConfig) => [modalConfig.uuid, modalConfig]),
      );
      const commands = new Map(Object.entries(store.get().commands));
      const reject = (detail: string) =>
        "Connection frame violates browser GUI safety limits: " + detail;
      const graphIsValid = () =>
        guiContainerGraphIsValid(
          projection.configs,
          modals,
          projection.tabOwnerFromUuid,
          MAX_GUI_CONTAINER_DEPTH,
        );
      type BatchKind = "gui" | "modal" | "command" | "tab";
      const batchKind = (message: Message): BatchKind | null => {
        if (isGuiComponentMessage(message)) return "gui";
        if (message.type === "GuiModalMessage") return "modal";
        if (message.type === "RegisterCommandMessage") return "command";
        if (
          message.type === "GuiTabMessage" ||
          message.type === "GuiTabUpdateMessage"
        ) {
          return "tab";
        }
        return null;
      };
      let pendingBatchKind: BatchKind | null = null;

      for (const message of messages) {
        const nextBatchKind = batchKind(message);
        if (
          pendingBatchKind !== null &&
          pendingBatchKind !== nextBatchKind &&
          !graphIsValid()
        ) {
          return reject(
            "GUI container graph has an invalid dispatch-batch prefix",
          );
        }
        pendingBatchKind = nextBatchKind;
        if (isGuiComponentMessage(message)) {
          const previous = projection.configs.get(message.uuid);
          if (
            projection.tabOwnerFromUuid.has(message.uuid) ||
            modals.has(message.uuid) ||
            message.uuid === ROOT_GUI_CONTAINER_ID
          ) {
            return reject("GUI component collides with another GUI owner");
          }
          const candidate = effectiveGuiCreate(message, previous);
          if (candidate === null || !guiConfigWithinEntityLimits(candidate)) {
            return reject("GUI component snapshot or entity limit is invalid");
          }
          if (
            previous === undefined &&
            projection.configs.size >= MAX_BROWSER_LIVE_GUI_COMPONENTS
          ) {
            return reject("GUI component owner limit exceeded");
          }
          setProjectedGuiConfig(projection, candidate);
          if (!guiConfigCostWithinBrowserLimits(projection.cost)) {
            return reject("GUI component aggregate budget exceeded");
          }
          continue;
        }
        switch (message.type) {
          case "GuiTabMessage":
          case "GuiTabUpdateMessage": {
            const detail = projectGuiTabLifecycle(projection, modals, message);
            if (detail !== null) return reject(detail);
            break;
          }
          case "GuiUpdateMessage": {
            if (
              projection.tabOwnerFromUuid.has(message.uuid) ||
              Object.hasOwn(message.updates, "_tabs")
            ) {
              return reject(
                "tab metadata may only change through tab lifecycle messages",
              );
            }
            const previous = projection.configs.get(message.uuid);
            if (previous === undefined) break;
            const candidate = validUpdatedGuiConfig(previous, message.updates);
            if (candidate === null) {
              return reject("GUI update violates its schema or entity limit");
            }
            setProjectedGuiConfig(projection, candidate);
            if (!guiConfigCostWithinBrowserLimits(projection.cost)) {
              return reject("GUI update exceeds the aggregate budget");
            }
            break;
          }
          case "GuiRemoveMessage":
            if (!removalTombstonesAreValid(message)) {
              return reject("GUI removal tombstones are invalid");
            }
            if (
              message.uuid === ROOT_GUI_CONTAINER_ID ||
              modals.has(message.uuid) ||
              removalDescendants(message).some(
                (uuid) =>
                  uuid === ROOT_GUI_CONTAINER_ID ||
                  modals.has(uuid) ||
                  projection.tabOwnerFromUuid.has(uuid),
              ) ||
              removalTabs(message).some(
                (uuid) =>
                  projection.configs.has(uuid) ||
                  modals.has(uuid) ||
                  uuid === ROOT_GUI_CONTAINER_ID,
              )
            ) {
              return reject("GUI removal tombstones cross owner namespaces");
            }
            projectGuiRemoval(
              projection,
              [message.uuid, ...removalDescendants(message)],
              [message.uuid],
              removalTabs(message),
            );
            break;
          case "GuiModalMessage":
            if (
              projection.configs.has(message.uuid) ||
              projection.tabOwnerFromUuid.has(message.uuid) ||
              message.uuid === ROOT_GUI_CONTAINER_ID ||
              !guiModalWithinEntityLimits(message) ||
              (!modals.has(message.uuid) &&
                modals.size >= MAX_BROWSER_LIVE_GUI_MODALS)
            ) {
              return reject("modal owner or string limit exceeded");
            }
            projection.cost = addGuiConfigCosts(
              modals.has(message.uuid)
                ? subtractGuiConfigCosts(
                    projection.cost,
                    guiModalCost(modals.get(message.uuid)!),
                  )
                : projection.cost,
              guiModalCost(message),
            );
            if (!guiConfigCostWithinBrowserLimits(projection.cost)) {
              return reject("modal exceeds the aggregate UI text budget");
            }
            modals.set(message.uuid, message);
            break;
          case "GuiCloseModalMessage": {
            if (!removalTombstonesAreValid(message)) {
              return reject("modal removal tombstones are invalid");
            }
            if (
              message.uuid === ROOT_GUI_CONTAINER_ID ||
              projection.configs.has(message.uuid) ||
              projection.tabOwnerFromUuid.has(message.uuid) ||
              removalDescendants(message).some(
                (uuid) =>
                  uuid === ROOT_GUI_CONTAINER_ID ||
                  modals.has(uuid) ||
                  projection.tabOwnerFromUuid.has(uuid),
              ) ||
              removalTabs(message).some(
                (uuid) =>
                  projection.configs.has(uuid) ||
                  modals.has(uuid) ||
                  uuid === ROOT_GUI_CONTAINER_ID,
              )
            ) {
              return reject("modal removal tombstones cross owner namespaces");
            }
            const previous = modals.get(message.uuid);
            if (previous !== undefined) {
              projection.cost = subtractGuiConfigCosts(
                projection.cost,
                guiModalCost(previous),
              );
            }
            modals.delete(message.uuid);
            projectGuiRemoval(
              projection,
              removalDescendants(message),
              [message.uuid],
              removalTabs(message),
            );
            break;
          }
          case "RegisterCommandMessage":
            if (
              !guiCommandWithinEntityLimits(message) ||
              (!commands.has(message.uuid) &&
                commands.size >= MAX_BROWSER_LIVE_GUI_COMMANDS)
            ) {
              return reject("command owner or string limit exceeded");
            }
            projection.cost = addGuiConfigCosts(
              commands.has(message.uuid)
                ? subtractGuiConfigCosts(
                    projection.cost,
                    guiCommandCost(commands.get(message.uuid)!),
                  )
                : projection.cost,
              guiCommandCost(message),
            );
            if (!guiConfigCostWithinBrowserLimits(projection.cost)) {
              return reject("command exceeds the aggregate UI text budget");
            }
            commands.set(message.uuid, message);
            break;
          case "CommandUpdateMessage": {
            const previous = commands.get(message.uuid);
            if (previous === undefined) break;
            const accepted = emptyRecord<unknown>();
            for (const [key, value] of Object.entries(message.updates)) {
              if (Object.hasOwn(previous.props, key)) accepted[key] = value;
            }
            const candidate: RegisterCommandMessage = {
              ...previous,
              props: { ...previous.props, ...accepted },
            };
            try {
              validateMessage(candidate);
            } catch {
              return reject("command update violates its schema");
            }
            if (!guiCommandWithinEntityLimits(candidate)) {
              return reject("command update exceeds its string limit");
            }
            projection.cost = addGuiConfigCosts(
              subtractGuiConfigCosts(projection.cost, guiCommandCost(previous)),
              guiCommandCost(candidate),
            );
            if (!guiConfigCostWithinBrowserLimits(projection.cost)) {
              return reject(
                "command update exceeds the aggregate UI text budget",
              );
            }
            commands.set(message.uuid, candidate);
            break;
          }
          case "RemoveCommandMessage": {
            const previous = commands.get(message.uuid);
            if (previous !== undefined) {
              projection.cost = subtractGuiConfigCosts(
                projection.cost,
                guiCommandCost(previous),
              );
            }
            commands.delete(message.uuid);
            break;
          }
        }
        if (nextBatchKind === null && !graphIsValid()) {
          return reject(
            "GUI container graph has an invalid dispatch-batch prefix",
          );
        }
      }

      if (!graphIsValid()) {
        return reject("GUI container graph is cyclic or deeper than 64");
      }
      return null;
    };

    const actions: GuiActions = {
      setTheme: (theme) => store.set({ theme }),
      addGui: (guiConfig) => addGuiBatch([guiConfig]),
      addGuiBatch,
      addModal: (modalConfig) => addModalBatch([modalConfig]),
      addModalBatch,
      applyTabLifecycleBatch,
      declareTab: (message) => applyTabLifecycleBatch([message]),
      updateTab: (message) => applyTabLifecycleBatch([message]),
      removeModal: (id, removedUuids = [], removedTabUuids = []) =>
        purgeGui(removedUuids, [id], removedTabUuids, id),
      removeGui: (id, removedUuids = [], removedTabUuids = []) =>
        purgeGui([id, ...removedUuids], [id], removedTabUuids),
      resetGui: () => {
        // Keep the theme to avoid a visual flash. Branding and every retained
        // GUI owner belong to the connection and must not cross reconnects.
        store.set({
          // The persistence namespace belongs to this connection. Clear it
          // until the next WorkspaceConfigurationMessage arrives so a new
          // session cannot read or write the previous workspace's layout.
          workspaceId: cleanGuiState.workspaceId,
          guiUuidSetFromContainerUuid:
            cleanGuiState.guiUuidSetFromContainerUuid,
          modals: cleanGuiState.modals,
          guiOrderFromUuid: cleanGuiState.guiOrderFromUuid,
          lastFormSubmit: cleanGuiState.lastFormSubmit,
          uploadsInProgress: cleanGuiState.uploadsInProgress,
          commands: cleanGuiState.commands,
        });
        aggregateGuiCost = {
          collectionItems: 0,
          retainedBytes: 0,
          textCodeUnits: 0,
        };
        tabOwnerFromUuid.clear();
        configStore.setAll({}, true);
      },
      updateUploadState: (uploadState) => {
        const state = store.get();
        const { componentId, transferUuid } = uploadState;
        const current = state.uploadsInProgress[componentId];
        // A new selection supersedes the previous one immediately. By
        // contrast, an ACK from a superseded transfer cannot recreate or
        // overwrite the progress belonging to the current selection.
        if (uploadState.filename !== undefined) {
          const uploadsInProgress = cloneRecord(state.uploadsInProgress);
          uploadsInProgress[componentId] = {
            transferUuid,
            uploadedBytes: uploadState.uploadedBytes,
            totalBytes: uploadState.totalBytes,
            filename: uploadState.filename,
          };
          store.set({
            uploadsInProgress,
          });
          return;
        }
        if (current === undefined || current.transferUuid !== transferUuid)
          return;
        const uploadsInProgress = cloneRecord(state.uploadsInProgress);
        uploadsInProgress[componentId] = {
          ...current,
          uploadedBytes: uploadState.uploadedBytes,
          totalBytes: uploadState.totalBytes,
        };
        store.set({ uploadsInProgress });
      },
      clearUploadState: (componentId, transferUuid) => {
        const state = store.get();
        if (state.uploadsInProgress[componentId]?.transferUuid !== transferUuid)
          return;
        const uploadsInProgress = cloneRecord(state.uploadsInProgress);
        delete uploadsInProgress[componentId];
        store.set({ uploadsInProgress });
      },
      addCommand: (command) => addCommandBatch([command]),
      addCommandBatch,
      updateCommand: (uuid, updates) => {
        const state = store.get();
        if (!Object.hasOwn(state.commands, uuid)) return;
        const failure = preflightMessageBatch([
          { type: "CommandUpdateMessage", uuid, updates },
        ]);
        if (failure !== null) {
          console.error(failure);
          return;
        }
        const existing = state.commands[uuid];
        const existingProps = existing.props as Record<string, unknown>;
        const acceptedUpdates = emptyRecord<unknown>();
        let changed = false;
        for (const [key, value] of Object.entries(updates)) {
          if (!Object.hasOwn(existing.props, key)) continue;
          acceptedUpdates[key] = value;
          if (!Object.is(existingProps[key], value)) changed = true;
        }
        if (!changed) return;
        const merged: RegisterCommandMessage = {
          ...existing,
          props: { ...existing.props, ...acceptedUpdates },
        };
        aggregateGuiCost = addGuiConfigCosts(
          subtractGuiConfigCosts(aggregateGuiCost, guiCommandCost(existing)),
          guiCommandCost(merged),
        );
        const commands = cloneRecord(state.commands);
        commands[uuid] = merged;
        store.set({ commands });
      },
      removeCommand: (uuid) => {
        const state = store.get();
        if (!Object.hasOwn(state.commands, uuid)) return;
        aggregateGuiCost = subtractGuiConfigCosts(
          aggregateGuiCost,
          guiCommandCost(state.commands[uuid]),
        );
        const next = cloneRecord(state.commands);
        delete next[uuid];
        store.set({ commands: next });
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
        updateGuiPropsBatch(new Map([[id, updates]]));
      },
      updateGuiPropsBatch,
      preflightMessageBatch,
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
          const guiOrderFromUuid = cloneRecord(state.guiOrderFromUuid);
          for (const [uuid, order] of changed) guiOrderFromUuid[uuid] = order;
          return { guiOrderFromUuid };
        });
      },
    };

    return { store, configStore, actions };
  })[0];
}

/** Type corresponding to the useGuiState hook return. */
export type UseGui = ReturnType<typeof useGuiState>;
