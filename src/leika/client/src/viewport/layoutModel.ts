/**
 * Serializable layout model for the viewport workspace.
 *
 * Pane content deliberately lives outside this tree. A leaf only references a
 * pane ID, which lets layouts be persisted without coupling the model to
 * React.
 */

import {
  isBoundedLayoutId,
  MAX_LAYOUT_CHILDREN,
  MAX_LAYOUT_DEPTH,
  MAX_LAYOUT_ITEMS,
} from "../persistenceLimits";

export type ViewportSplitDirection = "row" | "column";

export interface ViewportLayoutPane {
  type: "pane";
  pane_id: string;
}

export interface ViewportLayoutSplit {
  type: "split";
  direction: ViewportSplitDirection;
  children: ViewportLayoutNode[];
  /** Positive, normalized flex weights aligned with `children`. */
  weights: number[];
}

export type ViewportLayoutNode = ViewportLayoutPane | ViewportLayoutSplit;

/** Versioned persistence contract for a complete viewport layout. A null
 * root holds no panes, and the workspace shows its background. */
export interface ViewportLayout {
  version: 1;
  root: ViewportLayoutNode | null;
}

export type ViewportDropRegion = "center" | "top" | "bottom" | "left" | "right";

export type ViewportLayoutPath = readonly number[];

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

const isPositiveFinite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value > 0;

/** Return positive weights that sum to one. Missing/invalid entries use 1. */
export function normalizeViewportWeights(
  weights: readonly unknown[],
  childCount = weights.length,
): number[] {
  if (!Number.isInteger(childCount) || childCount <= 0) return [];

  // Already-normalized weights pass through bit-identical, so repeated
  // normalization (reconnect reconciles, visibility passes) cannot introduce
  // epsilon drift that defeats layout equality checks.
  if (
    weights.length === childCount &&
    weights.every(isPositiveFinite) &&
    Math.abs(
      (weights as readonly number[]).reduce((sum, weight) => sum + weight, 0) -
        1,
    ) <= 1e-12
  ) {
    return [...(weights as readonly number[])];
  }

  const sanitized = Array.from({ length: childCount }, (_, index) => {
    const weight = weights[index];
    return isPositiveFinite(weight) ? weight : 1;
  });
  // Scale first so valid but very large inputs cannot overflow the sum.
  const maximum = sanitized.reduce(
    (currentMaximum, weight) => Math.max(currentMaximum, weight),
    0,
  );
  const scaled = sanitized.map((weight) =>
    Math.max(weight / maximum, Number.MIN_VALUE),
  );
  const total = scaled.reduce((sum, weight) => sum + weight, 0);
  return scaled.map((weight) => Math.max(weight / total, Number.MIN_VALUE));
}

/** In-order pane IDs in a layout. */
export function collectViewportPaneIds(layout: ViewportLayout): string[] {
  return layout.root === null ? [] : collectPaneIds(layout.root);
}

function collectPaneIds(node: ViewportLayoutNode): string[] {
  if (node.type === "pane") return [node.pane_id];
  return node.children.flatMap(collectPaneIds);
}

export function hasViewportPane(
  layout: ViewportLayout,
  paneId: string,
): boolean {
  return layout.root !== null && hasPane(layout.root, paneId);
}

function hasPane(node: ViewportLayoutNode, paneId: string): boolean {
  if (node.type === "pane") return node.pane_id === paneId;
  return node.children.some((child) => hasPane(child, paneId));
}

function pane(paneId: string): ViewportLayoutPane {
  return { type: "pane", pane_id: paneId };
}

/**
 * Build a canonical split. Single children are promoted and nested splits on
 * the same axis are flattened while retaining their relative proportions.
 */
function makeSplit(
  direction: ViewportSplitDirection,
  children: readonly ViewportLayoutNode[],
  weights: readonly unknown[],
): ViewportLayoutNode | null {
  if (children.length === 0) return null;
  if (children.length === 1) return children[0];

  const flattenedChildren: ViewportLayoutNode[] = [];
  const flattenedWeights: number[] = [];
  const parentWeights = normalizeViewportWeights(weights, children.length);

  children.forEach((child, index) => {
    if (child.type === "split" && child.direction === direction) {
      const childWeights = normalizeViewportWeights(
        child.weights,
        child.children.length,
      );
      child.children.forEach((grandchild, grandchildIndex) => {
        flattenedChildren.push(grandchild);
        flattenedWeights.push(
          parentWeights[index] * childWeights[grandchildIndex],
        );
      });
      return;
    }

    flattenedChildren.push(child);
    flattenedWeights.push(parentWeights[index]);
  });

  if (flattenedChildren.length === 1) return flattenedChildren[0];
  return {
    type: "split",
    direction,
    children: flattenedChildren,
    weights: normalizeViewportWeights(
      flattenedWeights,
      flattenedChildren.length,
    ),
  };
}

interface ParseContext {
  readonly allowedPaneIds: ReadonlySet<string> | null;
  readonly seenPaneIds: Set<string>;
  readonly seenObjects: WeakSet<object>;
  visitedNodes: number;
}

/** Parse a serialized value, discarding invalid, unknown, or duplicate leaves. */
function parseLayout(
  value: unknown,
  context: ParseContext,
  depth = 1,
): ViewportLayoutNode | null {
  if (
    !isRecord(value) ||
    depth > MAX_LAYOUT_DEPTH ||
    context.visitedNodes >= MAX_LAYOUT_ITEMS
  )
    return null;
  if (context.seenObjects.has(value)) return null;
  context.seenObjects.add(value);
  context.visitedNodes += 1;

  if (value.type === "pane") {
    const paneId = value.pane_id;
    if (
      !isBoundedLayoutId(paneId) ||
      (context.allowedPaneIds !== null &&
        !context.allowedPaneIds.has(paneId)) ||
      context.seenPaneIds.has(paneId)
    ) {
      return null;
    }
    context.seenPaneIds.add(paneId);
    return pane(paneId);
  }

  if (
    value.type !== "split" ||
    (value.direction !== "row" && value.direction !== "column") ||
    !Array.isArray(value.children) ||
    value.children.length > MAX_LAYOUT_CHILDREN
  ) {
    return null;
  }

  const rawWeights =
    Array.isArray(value.weights) && value.weights.length <= MAX_LAYOUT_CHILDREN
      ? value.weights
      : [];
  const children: ViewportLayoutNode[] = [];
  const weights: unknown[] = [];
  value.children.forEach((rawChild, index) => {
    const parsedChild = parseLayout(rawChild, context, depth + 1);
    if (parsedChild === null) return;
    children.push(parsedChild);
    weights.push(rawWeights[index]);
  });

  if (children.length === 0) return null;
  if (children.length === 1) return children[0];
  // Preserve valid serialized nesting. A nested same-axis
  // split is a meaningful resizable group, not merely redundant structure.
  return {
    type: "split",
    direction: value.direction,
    children,
    weights: normalizeViewportWeights(weights, children.length),
  };
}

/**
 * Parse a persisted browser layout without knowing the current server panes.
 * Membership is reconciled separately when the server snapshot arrives.
 */
export function normalizeViewportLayout(value: unknown): ViewportLayout {
  const serializedRoot =
    isRecord(value) && value.version === 1 ? value.root : undefined;
  const root = parseLayout(serializedRoot, {
    allowedPaneIds: null,
    seenPaneIds: new Set<string>(),
    seenObjects: new WeakSet<object>(),
    visitedNodes: 0,
  });
  return { version: 1, root };
}

/**
 * Reconcile an arbitrary serialized layout with the panes currently visible
 * in this client.
 *
 * Unknown and duplicate leaves are removed. Malformed splits are collapsed,
 * weights are repaired, and missing panes are inserted in deterministic
 * `visiblePaneIds` order. With no visible panes the layout is empty.
 */
export function reconcileViewportLayout(
  value: unknown,
  visiblePaneIds: readonly string[],
): ViewportLayout {
  const orderedPaneIds: string[] = [];
  const allowedPaneIds = new Set<string>();
  for (const paneId of visiblePaneIds) {
    if (
      orderedPaneIds.length >= MAX_LAYOUT_ITEMS ||
      !isBoundedLayoutId(paneId) ||
      allowedPaneIds.has(paneId)
    )
      continue;
    allowedPaneIds.add(paneId);
    orderedPaneIds.push(paneId);
  }
  const seenPaneIds = new Set<string>();
  const serializedRoot =
    isRecord(value) && value.version === 1 ? value.root : undefined;
  let layout = parseLayout(serializedRoot, {
    allowedPaneIds,
    seenPaneIds,
    seenObjects: new WeakSet<object>(),
    visitedNodes: 0,
  });

  const firstPaneId = orderedPaneIds[0];
  if (firstPaneId === undefined) return { version: 1, root: null };
  if (!seenPaneIds.has(firstPaneId)) {
    layout =
      layout === null
        ? pane(firstPaneId)
        : makeSplit("row", [pane(firstPaneId), layout], [1, 1]);
    seenPaneIds.add(firstPaneId);
  }

  // Advance the anchor as panes are inserted so multiple missing panes keep
  // deterministic registry order beside the first pane.
  let anchorPaneId = firstPaneId;
  for (const paneId of orderedPaneIds) {
    if (seenPaneIds.has(paneId)) continue;
    layout = insertPaneAtEdge(layout!, paneId, anchorPaneId, "right");
    seenPaneIds.add(paneId);
    anchorPaneId = paneId;
  }

  // The first-pane insertion above guarantees a non-null layout.
  return { version: 1, root: layout! };
}

function sameLayoutNode(
  left: ViewportLayoutNode | null,
  right: ViewportLayoutNode | null,
): boolean {
  if (left === right) return true;
  if (left === null || right === null || left.type !== right.type) return false;
  if (left.type === "pane" && right.type === "pane") {
    return left.pane_id === right.pane_id;
  }
  if (left.type === "split" && right.type === "split") {
    return (
      left.direction === right.direction &&
      left.children.length === right.children.length &&
      left.weights.length === right.weights.length &&
      left.weights.every((weight, index) => weight === right.weights[index]) &&
      left.children.every((child, index) =>
        sameLayoutNode(child, right.children[index]),
      )
    );
  }
  return false;
}

/** Structural equality for normalized layouts. */
export function sameViewportLayout(
  left: ViewportLayout,
  right: ViewportLayout,
): boolean {
  return left === right || sameLayoutNode(left.root, right.root);
}

interface RemoveResult {
  readonly layout: ViewportLayoutNode | null;
  readonly removed: boolean;
}

function removePane(layout: ViewportLayoutNode, paneId: string): RemoveResult {
  if (layout.type === "pane") {
    return layout.pane_id === paneId
      ? { layout: null, removed: true }
      : { layout, removed: false };
  }

  const children: ViewportLayoutNode[] = [];
  const weights: number[] = [];
  let removed = false;
  layout.children.forEach((child, index) => {
    const result = removePane(child, paneId);
    removed ||= result.removed;
    if (result.layout !== null) {
      children.push(result.layout);
      weights.push(layout.weights[index]);
    }
  });

  if (!removed) return { layout, removed: false };
  return { layout: makeSplit(layout.direction, children, weights), removed };
}

/** Remove a pane and collapse any split left with fewer than two children. */
export function removeViewportPane(
  layout: ViewportLayout,
  paneId: string,
): ViewportLayout {
  if (layout.root === null) return layout;
  const result = removePane(layout.root, paneId);
  return result.removed ? { ...layout, root: result.layout } : layout;
}

function regionDirection(
  region: Exclude<ViewportDropRegion, "center">,
): ViewportSplitDirection {
  return region === "left" || region === "right" ? "row" : "column";
}

function regionIsBefore(
  region: Exclude<ViewportDropRegion, "center">,
): boolean {
  return region === "left" || region === "top";
}

interface InsertResult {
  readonly layout: ViewportLayoutNode;
  readonly inserted: boolean;
}

function insertAtTarget(
  layout: ViewportLayoutNode,
  pane: ViewportLayoutPane,
  targetPaneId: string,
  region: Exclude<ViewportDropRegion, "center">,
): InsertResult {
  const direction = regionDirection(region);
  const before = regionIsBefore(region);

  if (layout.type === "pane") {
    if (layout.pane_id !== targetPaneId) {
      return { layout, inserted: false };
    }
    const children = before ? [pane, layout] : [layout, pane];
    return {
      layout: makeSplit(direction, children, [1, 1])!,
      inserted: true,
    };
  }

  // Inserting beside a direct child on the same axis is a reorder/flat split,
  // not a redundant nested split. Divide the target's allocation evenly.
  if (layout.direction === direction) {
    const targetIndex = layout.children.findIndex(
      (child) => child.type === "pane" && child.pane_id === targetPaneId,
    );
    if (targetIndex !== -1) {
      const children = [...layout.children];
      const weights = normalizeViewportWeights(
        layout.weights,
        layout.children.length,
      );
      const targetWeight = weights[targetIndex];
      const insertIndex = targetIndex + (before ? 0 : 1);
      children.splice(insertIndex, 0, pane);
      weights[targetIndex] = targetWeight / 2;
      weights.splice(insertIndex, 0, targetWeight / 2);
      return {
        layout: makeSplit(direction, children, weights)!,
        inserted: true,
      };
    }
  }

  for (let index = 0; index < layout.children.length; index++) {
    const result = insertAtTarget(
      layout.children[index],
      pane,
      targetPaneId,
      region,
    );
    if (!result.inserted) continue;
    const children = [...layout.children];
    children[index] = result.layout;
    return {
      layout: makeSplit(layout.direction, children, layout.weights)!,
      inserted: true,
    };
  }

  return { layout, inserted: false };
}

interface ReorderResult {
  readonly layout: ViewportLayoutNode;
  readonly reordered: boolean;
}

/** Preserve weights when a pane is reordered within the same split. */
function reorderSiblingPane(
  layout: ViewportLayoutNode,
  paneId: string,
  targetPaneId: string,
  region: Exclude<ViewportDropRegion, "center">,
): ReorderResult {
  if (layout.type === "pane") return { layout, reordered: false };

  const direction = regionDirection(region);
  if (layout.direction === direction) {
    const sourceIndex = layout.children.findIndex(
      (child) => child.type === "pane" && child.pane_id === paneId,
    );
    const targetIndex = layout.children.findIndex(
      (child) => child.type === "pane" && child.pane_id === targetPaneId,
    );
    if (sourceIndex !== -1 && targetIndex !== -1) {
      const children = [...layout.children];
      const weights = [...layout.weights];
      const [source] = children.splice(sourceIndex, 1);
      const [sourceWeight] = weights.splice(sourceIndex, 1);
      const shiftedTargetIndex = children.findIndex(
        (child) => child.type === "pane" && child.pane_id === targetPaneId,
      );
      const insertIndex = shiftedTargetIndex + (regionIsBefore(region) ? 0 : 1);
      children.splice(insertIndex, 0, source);
      weights.splice(insertIndex, 0, sourceWeight);
      return {
        layout: {
          ...layout,
          children,
          weights: normalizeViewportWeights(weights, children.length),
        },
        reordered: true,
      };
    }
  }

  for (let index = 0; index < layout.children.length; index++) {
    const result = reorderSiblingPane(
      layout.children[index],
      paneId,
      targetPaneId,
      region,
    );
    if (!result.reordered) continue;
    const children = [...layout.children];
    children[index] = result.layout;
    return { layout: { ...layout, children }, reordered: true };
  }
  return { layout, reordered: false };
}

/**
 * Insert a new pane, or move an existing pane, at an edge of a target pane.
 * Unknown targets are a safe no-op. Same-axis siblings are reordered without
 * changing their sizes; other moves detach, collapse, and reinsert the pane.
 */
function insertPaneAtEdge(
  layout: ViewportLayoutNode,
  paneId: string,
  targetPaneId: string,
  region: Exclude<ViewportDropRegion, "center">,
): ViewportLayoutNode {
  if (paneId === targetPaneId || !hasPane(layout, targetPaneId)) {
    return layout;
  }

  if (hasPane(layout, paneId)) {
    const reordered = reorderSiblingPane(layout, paneId, targetPaneId, region);
    if (reordered.reordered) return reordered.layout;
  }

  const detached = removePane(layout, paneId).layout ?? layout;
  const result = insertAtTarget(detached, pane(paneId), targetPaneId, region);
  // This should only be false for malformed duplicate layouts. Keep the
  // original in that case so a failed move can never lose a pane.
  return result.inserted ? result.layout : layout;
}

/** Insert a new pane, or move one, at an edge of a target pane. */
export function insertViewportPane(
  layout: ViewportLayout,
  paneId: string,
  targetPaneId: string,
  region: Exclude<ViewportDropRegion, "center">,
): ViewportLayout {
  if (layout.root === null) return layout;
  const root = insertPaneAtEdge(layout.root, paneId, targetPaneId, region);
  return root === layout.root ? layout : { ...layout, root };
}

/**
 * Place a pane that is not yet in the layout at an edge of `relativeTo`, or
 * of the last pane when that one is absent. In an empty layout the pane fills
 * the workspace.
 */
export function placeViewportPane(
  layout: ViewportLayout,
  paneId: string,
  relativeTo: string | null,
  region: Exclude<ViewportDropRegion, "center">,
): ViewportLayout {
  if (layout.root === null) return { ...layout, root: pane(paneId) };
  const paneIds = collectPaneIds(layout.root);
  const target =
    relativeTo !== null && paneIds.includes(relativeTo)
      ? relativeTo
      : paneIds[paneIds.length - 1];
  return insertViewportPane(layout, paneId, target, region);
}

function swapPaneIds(
  layout: ViewportLayoutNode,
  paneId: string,
  targetPaneId: string,
): ViewportLayoutNode {
  if (layout.type === "pane") {
    if (layout.pane_id === paneId) return pane(targetPaneId);
    if (layout.pane_id === targetPaneId) return pane(paneId);
    return layout;
  }

  const children = layout.children.map((child) =>
    swapPaneIds(child, paneId, targetPaneId),
  );
  return children.every((child, index) => child === layout.children[index])
    ? layout
    : { ...layout, children };
}

/**
 * Apply a pane-header drop. Center swaps the two pane positions; edge regions
 * move the source pane beside the target (or insert it when it is new).
 */
export function dropViewportPane(
  layout: ViewportLayout,
  paneId: string,
  targetPaneId: string,
  region: ViewportDropRegion,
): ViewportLayout {
  if (region !== "center") {
    return insertViewportPane(layout, paneId, targetPaneId, region);
  }
  if (
    layout.root === null ||
    paneId === targetPaneId ||
    !hasPane(layout.root, paneId) ||
    !hasPane(layout.root, targetPaneId)
  ) {
    return layout;
  }
  return { ...layout, root: swapPaneIds(layout.root, paneId, targetPaneId) };
}

function setSplitWeightsAtPath(
  layout: ViewportLayoutNode,
  path: ViewportLayoutPath,
  weights: readonly unknown[],
): ViewportLayoutNode {
  if (path.length === 0) {
    if (layout.type !== "split" || weights.length !== layout.children.length) {
      return layout;
    }
    const normalized = normalizeViewportWeights(
      weights,
      layout.children.length,
    );
    return normalized.every((weight, index) => weight === layout.weights[index])
      ? layout
      : { ...layout, weights: normalized };
  }

  if (layout.type !== "split") return layout;
  const [childIndex, ...rest] = path;
  if (
    !Number.isInteger(childIndex) ||
    childIndex < 0 ||
    childIndex >= layout.children.length
  ) {
    return layout;
  }
  const child = setSplitWeightsAtPath(
    layout.children[childIndex],
    rest,
    weights,
  );
  if (child === layout.children[childIndex]) return layout;
  const children = [...layout.children];
  children[childIndex] = child;
  return { ...layout, children };
}

/** Replace a split's weights, addressed by child-index path from the root. */
export function setViewportSplitWeights(
  layout: ViewportLayout,
  path: ViewportLayoutPath,
  weights: readonly unknown[],
): ViewportLayout {
  if (layout.root === null) return layout;
  const root = setSplitWeightsAtPath(layout.root, path, weights);
  return root === layout.root ? layout : { ...layout, root };
}

function equalizePanesInNode(
  node: ViewportLayoutNode,
  paneIds: ReadonlySet<string>,
): ViewportLayoutNode {
  if (node.type === "pane") return node;

  const children = node.children.map((child) =>
    equalizePanesInNode(child, paneIds),
  );
  let result = children.every((child, index) => child === node.children[index])
    ? node
    : { ...node, children };

  const memberIndices = result.children.flatMap((child, index) =>
    child.type === "pane" && paneIds.has(child.pane_id) ? [index] : [],
  );
  if (memberIndices.length >= 2) {
    const weights = normalizeViewportWeights(
      result.weights,
      result.children.length,
    );
    const combined = memberIndices.reduce(
      (sum, index) => sum + weights[index],
      0,
    );
    const share = combined / memberIndices.length;
    memberIndices.forEach((index) => (weights[index] = share));
    if (weights.some((weight, index) => weight !== result.weights[index])) {
      result = { ...result, weights };
    }
  }
  return result;
}

/**
 * Redistribute the combined weight of the named panes equally, wherever two
 * or more of them are leaves of the same split. Panes outside the group keep
 * their exact shares; named panes that are missing or not siblings are left
 * untouched.
 */
export function equalizeViewportPanes(
  layout: ViewportLayout,
  paneIds: readonly string[],
): ViewportLayout {
  if (paneIds.length < 2 || layout.root === null) return layout;
  const root = equalizePanesInNode(layout.root, new Set(paneIds));
  return root === layout.root ? layout : { ...layout, root };
}
