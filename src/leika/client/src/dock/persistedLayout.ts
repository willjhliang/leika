import {
  type DockLayout,
  type DockNode,
  type FloatingWindow,
  type TabGroup,
} from "./types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonemptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isPositiveNumber(value: unknown): value is number {
  return isFiniteNumber(value) && value > 0;
}

/** Validate a browser-stored dock layout before it reaches layout operations.
 *
 * Dock operations assume their input already satisfies the model invariants:
 * every group has exactly one owner, panels appear once, active tabs are live,
 * and every referenced ID exists. Persistence is an untrusted boundary, so a
 * malformed or hand-edited payload is rejected as a whole rather than partly
 * repaired into a surprising arrangement.
 */
export function normalizeDockLayout(value: unknown): DockLayout | null {
  if (!isRecord(value) || !isRecord(value.groups)) return null;

  const occupiedIds = new Set<string>();
  const panelIds = new Set<string>();
  const groups: Record<string, TabGroup> = {};

  for (const [groupId, rawGroup] of Object.entries(value.groups)) {
    if (
      !isNonemptyString(groupId) ||
      !isRecord(rawGroup) ||
      rawGroup.id !== groupId ||
      !Array.isArray(rawGroup.panelIds) ||
      !rawGroup.panelIds.every(isNonemptyString) ||
      typeof rawGroup.activeId !== "string" ||
      (rawGroup.collapsed !== undefined &&
        typeof rawGroup.collapsed !== "boolean") ||
      (rawGroup.collapsedByParent !== undefined &&
        typeof rawGroup.collapsedByParent !== "boolean") ||
      occupiedIds.has(groupId)
    ) {
      return null;
    }
    const uniquePanels = new Set(rawGroup.panelIds);
    if (
      uniquePanels.size !== rawGroup.panelIds.length ||
      rawGroup.panelIds.some((panelId) => panelIds.has(panelId)) ||
      (rawGroup.panelIds.length > 0 &&
        !uniquePanels.has(rawGroup.activeId as string))
    ) {
      return null;
    }
    rawGroup.panelIds.forEach((panelId) => panelIds.add(panelId));
    occupiedIds.add(groupId);
    groups[groupId] = {
      id: groupId,
      panelIds: [...rawGroup.panelIds],
      activeId: rawGroup.activeId,
      ...(rawGroup.collapsed === undefined
        ? {}
        : { collapsed: rawGroup.collapsed }),
      ...(rawGroup.collapsedByParent === undefined
        ? {}
        : { collapsedByParent: rawGroup.collapsedByParent }),
    };
  }

  const ownedGroups = new Set<string>();
  const claimGroup = (groupId: unknown): groupId is string => {
    if (
      !isNonemptyString(groupId) ||
      groups[groupId] === undefined ||
      ownedGroups.has(groupId)
    ) {
      return false;
    }
    ownedGroups.add(groupId);
    return true;
  };

  const readNode = (rawNode: unknown): DockNode | null => {
    if (
      !isRecord(rawNode) ||
      !isNonemptyString(rawNode.id) ||
      occupiedIds.has(rawNode.id) ||
      !isPositiveNumber(rawNode.weight)
    ) {
      return null;
    }
    occupiedIds.add(rawNode.id);
    if (rawNode.type === "leaf") {
      if (!claimGroup(rawNode.group)) return null;
      return {
        type: "leaf",
        id: rawNode.id,
        group: rawNode.group,
        weight: rawNode.weight,
      };
    }
    if (
      rawNode.type !== "split" ||
      (rawNode.dir !== "row" && rawNode.dir !== "column") ||
      !Array.isArray(rawNode.children) ||
      rawNode.children.length < 2
    ) {
      return null;
    }
    const children: DockNode[] = [];
    for (const child of rawNode.children) {
      const parsed = readNode(child);
      if (parsed === null) return null;
      children.push(parsed);
    }
    return {
      type: "split",
      id: rawNode.id,
      dir: rawNode.dir,
      weight: rawNode.weight,
      children,
    };
  };

  if (!isRecord(value.docked)) return null;
  const rawDocked = value.docked;
  const readEdge = (edge: "left" | "right"): DockNode | null | undefined => {
    const raw = rawDocked[edge];
    if (raw === null) return null;
    return readNode(raw) ?? undefined;
  };
  const left = readEdge("left");
  const right = readEdge("right");
  if (left === undefined || right === undefined) return null;

  if (!Array.isArray(value.floating)) return null;
  const floating: FloatingWindow[] = [];
  for (const rawWindow of value.floating) {
    if (
      !isRecord(rawWindow) ||
      !isNonemptyString(rawWindow.id) ||
      occupiedIds.has(rawWindow.id) ||
      !isFiniteNumber(rawWindow.x) ||
      !isFiniteNumber(rawWindow.y) ||
      !isPositiveNumber(rawWindow.width) ||
      (rawWindow.height !== undefined && !isPositiveNumber(rawWindow.height)) ||
      !Array.isArray(rawWindow.stack) ||
      rawWindow.stack.length === 0
    ) {
      return null;
    }
    occupiedIds.add(rawWindow.id);
    const stack: string[] = [];
    for (const groupId of rawWindow.stack) {
      if (!claimGroup(groupId)) return null;
      stack.push(groupId);
    }
    if (new Set(stack).size !== stack.length) return null;

    let stackWeights: Record<string, number> | undefined;
    if (rawWindow.stackWeights !== undefined) {
      if (!isRecord(rawWindow.stackWeights)) return null;
      stackWeights = {};
      for (const [groupId, weight] of Object.entries(rawWindow.stackWeights)) {
        if (!stack.includes(groupId) || !isPositiveNumber(weight)) return null;
        stackWeights[groupId] = weight;
      }
    }
    floating.push({
      id: rawWindow.id,
      x: rawWindow.x,
      y: rawWindow.y,
      width: rawWindow.width,
      ...(rawWindow.height === undefined ? {} : { height: rawWindow.height }),
      stack,
      ...(stackWeights === undefined ? {} : { stackWeights }),
    });
  }

  let areas: DockLayout["areas"];
  const areaGroups = new Set<string>();
  if (value.areas === undefined) {
    areas = {};
  } else {
    if (!isRecord(value.areas)) return null;
    areas = {};
    for (const [areaId, rawArea] of Object.entries(value.areas)) {
      if (
        !isNonemptyString(areaId) ||
        !isRecord(rawArea) ||
        rawArea.id !== areaId ||
        !claimGroup(rawArea.group)
      ) {
        return null;
      }
      areas[areaId] = { id: areaId, group: rawArea.group };
      areaGroups.add(rawArea.group);
    }
  }

  if (
    ownedGroups.size !== Object.keys(groups).length ||
    Object.values(groups).some(
      (group) => group.panelIds.length === 0 && !areaGroups.has(group.id),
    )
  ) {
    return null;
  }

  let regionWidth: DockLayout["regionWidth"];
  if (value.regionWidth !== undefined) {
    if (
      !isRecord(value.regionWidth) ||
      !isPositiveNumber(value.regionWidth.left) ||
      !isPositiveNumber(value.regionWidth.right)
    ) {
      return null;
    }
    regionWidth = {
      left: value.regionWidth.left,
      right: value.regionWidth.right,
    };
  }

  return {
    groups,
    docked: { left, right },
    ...(regionWidth === undefined ? {} : { regionWidth }),
    floating,
    areas,
  };
}
