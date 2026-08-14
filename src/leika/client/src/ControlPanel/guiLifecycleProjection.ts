import {
  MAX_BROWSER_LIVE_GUI_TABS,
  MAX_GUI_COLLECTION_ITEMS,
  addGuiConfigCosts,
  guiConfigCost,
  guiConfigCostWithinBrowserLimits,
  guiTabWithinEntityLimits,
  subtractGuiConfigCosts,
  type GuiConfigCost,
} from "../guiLimits";
import { isBoundedLayoutId } from "../persistenceLimits";
import type {
  GuiComponentMessage,
  GuiModalMessage,
  GuiTabGroupMessage,
  GuiTabMessage,
  GuiTabUpdateMessage,
} from "../WebsocketMessages";
import { ROOT_GUI_CONTAINER_ID } from "./guiConstants";

type GuiTabDescriptor = GuiTabGroupMessage["props"]["_tabs"][number];
export type GuiTabLifecycleMessage = GuiTabMessage | GuiTabUpdateMessage;

export interface GuiProjection {
  configs: Map<string, GuiComponentMessage>;
  childrenByContainer: Map<string, Set<string>>;
  tabOwnerFromUuid: Map<string, string>;
  tabUuidsFromGroupUuid: Map<string, Set<string>>;
  cost: GuiConfigCost;
}

function addToContainerIndex(
  index: Map<string, Set<string>>,
  config: GuiComponentMessage,
): void {
  let children = index.get(config.container_uuid);
  if (children === undefined) {
    children = new Set();
    index.set(config.container_uuid, children);
  }
  children.add(config.uuid);
}

function removeFromContainerIndex(
  index: Map<string, Set<string>>,
  config: GuiComponentMessage,
): void {
  const children = index.get(config.container_uuid);
  children?.delete(config.uuid);
  if (children?.size === 0) index.delete(config.container_uuid);
}

export function createGuiProjection(
  currentConfigs: Iterable<readonly [string, GuiComponentMessage]>,
  currentTabOwners: ReadonlyMap<string, string>,
  currentCost: GuiConfigCost,
): GuiProjection {
  const configs = new Map(currentConfigs);
  const childrenByContainer = new Map<string, Set<string>>();
  for (const config of configs.values()) {
    addToContainerIndex(childrenByContainer, config);
  }
  const tabOwnerFromUuid = new Map(currentTabOwners);
  const tabUuidsFromGroupUuid = new Map<string, Set<string>>();
  for (const [tabUuid, groupUuid] of tabOwnerFromUuid) {
    let tabs = tabUuidsFromGroupUuid.get(groupUuid);
    if (tabs === undefined) {
      tabs = new Set();
      tabUuidsFromGroupUuid.set(groupUuid, tabs);
    }
    tabs.add(tabUuid);
  }
  return {
    configs,
    childrenByContainer,
    tabOwnerFromUuid,
    tabUuidsFromGroupUuid,
    cost: currentCost,
  };
}

export function effectiveGuiCreate(
  incoming: GuiComponentMessage,
  previous: GuiComponentMessage | undefined,
): GuiComponentMessage | null {
  if (incoming.type === "GuiTabGroupMessage") {
    // Tab descriptors are derived exclusively from the flat lifecycle. A
    // repeated group declaration keeps descriptors already owned by the
    // current incarnation instead of erasing them with its empty wire anchor.
    if (incoming.props._tabs.length !== 0) return null;
    if (previous?.type === "GuiTabGroupMessage") {
      return {
        ...incoming,
        props: { ...incoming.props, _tabs: previous.props._tabs },
      };
    }
    return incoming;
  }
  // Replacing a live group without first removing its tab entities would
  // strand their containers. Empty groups retain the legacy component-upsert
  // semantics used by the rest of the GUI protocol.
  if (
    previous?.type === "GuiTabGroupMessage" &&
    previous.props._tabs.length !== 0
  ) {
    return null;
  }
  return incoming;
}

export function setProjectedGuiConfig(
  projection: GuiProjection,
  config: GuiComponentMessage,
): void {
  const previous = projection.configs.get(config.uuid);
  if (previous !== undefined) {
    projection.cost = subtractGuiConfigCosts(
      projection.cost,
      guiConfigCost(previous),
    );
    removeFromContainerIndex(projection.childrenByContainer, previous);
  }
  projection.configs.set(config.uuid, config);
  addToContainerIndex(projection.childrenByContainer, config);
  projection.cost = addGuiConfigCosts(projection.cost, guiConfigCost(config));
}

function descriptorFromMessage(
  message: GuiTabLifecycleMessage,
): GuiTabDescriptor {
  return {
    label: message.label,
    icon_html: message.icon_html,
    container_id: message.uuid,
  };
}

/** Apply one tab declaration/update to a temporary projection.
 *
 * The returned text is deliberately detail-only; the GUI state owns the
 * connection-level error prefix used by all of its preflight failures.
 */
export function projectGuiTabLifecycle(
  projection: GuiProjection,
  modals: ReadonlyMap<string, GuiModalMessage>,
  message: GuiTabLifecycleMessage,
): string | null {
  if (
    !isBoundedLayoutId(message.uuid) ||
    !isBoundedLayoutId(message.group_uuid) ||
    !guiTabWithinEntityLimits(message)
  ) {
    return "tab declaration exceeds its identifier or string limit";
  }
  if (
    message.uuid === ROOT_GUI_CONTAINER_ID ||
    projection.configs.has(message.uuid) ||
    modals.has(message.uuid)
  ) {
    return "tab container collides with another GUI owner";
  }

  const group = projection.configs.get(message.group_uuid);
  if (group?.type !== "GuiTabGroupMessage") {
    return "tab declaration references a missing tab group";
  }
  const existingOwner = projection.tabOwnerFromUuid.get(message.uuid);
  if (existingOwner !== undefined && existingOwner !== message.group_uuid) {
    return "tab container is already owned by another group";
  }
  if (message.type === "GuiTabUpdateMessage" && existingOwner === undefined) {
    return "tab update precedes its declaration";
  }

  const matchingIndexes: number[] = [];
  for (let index = 0; index < group.props._tabs.length; index += 1) {
    if (group.props._tabs[index].container_id === message.uuid) {
      matchingIndexes.push(index);
    }
  }
  if (
    matchingIndexes.length > 1 ||
    (existingOwner === undefined) !== (matchingIndexes.length === 0)
  ) {
    return "tab declaration registry is inconsistent";
  }
  if (
    existingOwner === undefined &&
    (group.props._tabs.length >= MAX_GUI_COLLECTION_ITEMS ||
      projection.tabOwnerFromUuid.size >= MAX_BROWSER_LIVE_GUI_TABS)
  ) {
    return "tab declaration exceeds its group or page owner limit";
  }

  // A repeated create for the same owner is lifecycle-idempotent: it verifies
  // ownership but cannot overwrite metadata that a later update established.
  if (message.type === "GuiTabMessage" && existingOwner !== undefined) {
    return null;
  }

  const descriptor = descriptorFromMessage(message);
  const nextTabs = [...group.props._tabs];
  if (matchingIndexes.length === 0) nextTabs.push(descriptor);
  else nextTabs[matchingIndexes[0]] = descriptor;
  const candidate: GuiTabGroupMessage = {
    ...group,
    props: { ...group.props, _tabs: nextTabs },
  };
  const candidateCost = addGuiConfigCosts(
    subtractGuiConfigCosts(projection.cost, guiConfigCost(group)),
    guiConfigCost(candidate),
  );
  if (!guiConfigCostWithinBrowserLimits(candidateCost)) {
    return "tab declaration exceeds the aggregate GUI budget";
  }

  setProjectedGuiConfig(projection, candidate);
  if (existingOwner === undefined) {
    projection.tabOwnerFromUuid.set(message.uuid, message.group_uuid);
    let groupTabs = projection.tabUuidsFromGroupUuid.get(message.group_uuid);
    if (groupTabs === undefined) {
      groupTabs = new Set();
      projection.tabUuidsFromGroupUuid.set(message.group_uuid, groupTabs);
    }
    groupTabs.add(message.uuid);
  }
  return null;
}

export interface GuiRemovalProjection {
  removedComponents: ReadonlySet<string>;
  removedContainers: ReadonlySet<string>;
  removedTabs: ReadonlySet<string>;
}

/** Project a compact removal, including every descendant discovered locally. */
export function projectGuiRemoval(
  projection: GuiProjection,
  initialComponents: readonly string[],
  initialContainers: readonly string[],
  initialTabs: readonly string[],
): GuiRemovalProjection {
  const removedComponents = new Set<string>();
  const removedContainers = new Set<string>();
  const removedTabs = new Set<string>();
  const componentQueue: string[] = [];
  const containerQueue: string[] = [];
  const tabQueue: string[] = [];

  const queueComponent = (uuid: string) => {
    if (removedComponents.has(uuid)) return;
    removedComponents.add(uuid);
    componentQueue.push(uuid);
  };
  const queueContainer = (uuid: string) => {
    if (removedContainers.has(uuid)) return;
    removedContainers.add(uuid);
    containerQueue.push(uuid);
  };
  const queueTab = (uuid: string) => {
    if (removedTabs.has(uuid)) return;
    removedTabs.add(uuid);
    tabQueue.push(uuid);
  };
  for (const uuid of initialComponents) {
    if (projection.tabOwnerFromUuid.has(uuid)) queueTab(uuid);
    else queueComponent(uuid);
  }
  for (const uuid of initialContainers) queueContainer(uuid);
  for (const uuid of initialTabs) queueTab(uuid);

  let componentAt = 0;
  let containerAt = 0;
  let tabAt = 0;
  while (
    componentAt < componentQueue.length ||
    containerAt < containerQueue.length ||
    tabAt < tabQueue.length
  ) {
    while (tabAt < tabQueue.length) {
      queueContainer(tabQueue[tabAt++]);
    }
    while (containerAt < containerQueue.length) {
      const containerUuid = containerQueue[containerAt++];
      for (const uuid of projection.childrenByContainer.get(containerUuid) ??
        []) {
        queueComponent(uuid);
      }
    }
    while (componentAt < componentQueue.length) {
      const uuid = componentQueue[componentAt++];
      // Folder/form children use their component UUID as their container.
      queueContainer(uuid);
      const config = projection.configs.get(uuid);
      if (config?.type !== "GuiTabGroupMessage") continue;
      for (const tab of config.props._tabs) queueTab(tab.container_id);
      for (const tabUuid of projection.tabUuidsFromGroupUuid.get(uuid) ?? []) {
        queueTab(tabUuid);
      }
    }
  }

  for (const uuid of removedComponents) {
    const config = projection.configs.get(uuid);
    if (config === undefined) continue;
    projection.cost = subtractGuiConfigCosts(
      projection.cost,
      guiConfigCost(config),
    );
    removeFromContainerIndex(projection.childrenByContainer, config);
    projection.configs.delete(uuid);
  }

  const affectedGroupUuids = new Set<string>();
  for (const tabUuid of removedTabs) {
    const groupUuid = projection.tabOwnerFromUuid.get(tabUuid);
    projection.tabOwnerFromUuid.delete(tabUuid);
    if (groupUuid === undefined) continue;
    affectedGroupUuids.add(groupUuid);
    const groupTabs = projection.tabUuidsFromGroupUuid.get(groupUuid);
    groupTabs?.delete(tabUuid);
    if (groupTabs?.size === 0) {
      projection.tabUuidsFromGroupUuid.delete(groupUuid);
    }
  }

  // A surviving parent group loses all removed tab descriptors in the same
  // config-store transaction as the tab containers and their GUI subtrees.
  // Resolve groups from the reverse owner index instead of scanning every
  // component once per removal message.
  for (const groupUuid of affectedGroupUuids) {
    const config = projection.configs.get(groupUuid);
    if (config?.type !== "GuiTabGroupMessage") continue;
    const nextTabs = config.props._tabs.filter(
      (tab) => !removedTabs.has(tab.container_id),
    );
    if (nextTabs.length === config.props._tabs.length) continue;
    setProjectedGuiConfig(projection, {
      ...config,
      props: { ...config.props, _tabs: nextTabs },
    });
  }

  return { removedComponents, removedContainers, removedTabs };
}

/** Validate all component, modal, and explicit-tab ownership as one graph. */
export function guiContainerGraphIsValid(
  configs: ReadonlyMap<string, GuiComponentMessage>,
  modals: ReadonlyMap<string, GuiModalMessage>,
  tabOwnerFromUuid: ReadonlyMap<string, string>,
  maxDepth = 64,
): boolean {
  if (
    configs.has(ROOT_GUI_CONTAINER_ID) ||
    modals.has(ROOT_GUI_CONTAINER_ID) ||
    tabOwnerFromUuid.has(ROOT_GUI_CONTAINER_ID)
  ) {
    return false;
  }
  for (const modalUuid of modals.keys()) {
    if (configs.has(modalUuid) || tabOwnerFromUuid.has(modalUuid)) return false;
  }

  const descriptorOwnerFromUuid = new Map<string, string>();
  for (const config of configs.values()) {
    if (tabOwnerFromUuid.has(config.uuid) || modals.has(config.uuid))
      return false;
    if (config.type !== "GuiTabGroupMessage") continue;
    for (const tab of config.props._tabs) {
      if (
        !isBoundedLayoutId(tab.container_id) ||
        descriptorOwnerFromUuid.has(tab.container_id) ||
        configs.has(tab.container_id) ||
        modals.has(tab.container_id) ||
        tab.container_id === ROOT_GUI_CONTAINER_ID ||
        tabOwnerFromUuid.get(tab.container_id) !== config.uuid
      ) {
        return false;
      }
      descriptorOwnerFromUuid.set(tab.container_id, config.uuid);
    }
  }
  if (descriptorOwnerFromUuid.size !== tabOwnerFromUuid.size) return false;
  for (const [tabUuid, groupUuid] of tabOwnerFromUuid) {
    if (
      !isBoundedLayoutId(tabUuid) ||
      !isBoundedLayoutId(groupUuid) ||
      descriptorOwnerFromUuid.get(tabUuid) !== groupUuid
    ) {
      return false;
    }
  }

  const depthFromRoot = new Map<string, number>();
  const starts = [...configs.keys(), ...tabOwnerFromUuid.keys()];
  for (const start of starts) {
    if (depthFromRoot.has(start)) continue;
    const path = new Set<string>();
    const ordered: string[] = [];
    let current: string | undefined = start;
    let parentDepth = 0;
    while (current !== undefined) {
      const knownDepth = depthFromRoot.get(current);
      if (knownDepth !== undefined) {
        parentDepth = knownDepth;
        break;
      }
      if (path.has(current)) return false;
      path.add(current);
      ordered.push(current);

      const config = configs.get(current);
      if (config !== undefined) {
        const container = config.container_uuid;
        if (container === ROOT_GUI_CONTAINER_ID || modals.has(container)) break;
        const directParent = configs.get(container);
        if (directParent !== undefined) {
          if (
            directParent.type !== "GuiFolderMessage" &&
            directParent.type !== "GuiFormMessage"
          ) {
            return false;
          }
          current = container;
          continue;
        }
        if (!tabOwnerFromUuid.has(container)) return false;
        current = container;
        continue;
      }

      const groupUuid = tabOwnerFromUuid.get(current);
      if (groupUuid === undefined) return false;
      if (configs.get(groupUuid)?.type !== "GuiTabGroupMessage") return false;
      current = groupUuid;
    }
    for (let index = ordered.length - 1; index >= 0; index -= 1) {
      parentDepth += 1;
      if (parentDepth > maxDepth) return false;
      depthFromRoot.set(ordered[index], parentDepth);
    }
  }
  return true;
}
