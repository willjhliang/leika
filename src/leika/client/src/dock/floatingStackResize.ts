import { cascadeResize, weightedCellSizes } from "./layoutOps";
import { GroupId } from "./types";
import { cloneRecord, emptyRecord } from "../recordUtils";

const SIZE_EPSILON_PX = 1e-6;
/** Expanded floating-stack cells share only the space left after fixed
 * dividers and collapsed group chrome. Keeping this subtraction outside the
 * cascade helper makes its container contract explicit and testable. */
export function floatingStackCellBudget(
  containerPx: number,
  dividerHeights: readonly number[],
  collapsedCellHeights: readonly number[],
): number {
  const fixedChromePx = [...dividerHeights, ...collapsedCellHeights].reduce(
    (sum, height) => sum + height,
    0,
  );
  return Math.max(0, containerPx - fixedChromePx);
}

export interface FloatingStackResizeUpdate {
  weights: Record<GroupId, number>;
  pinAutoHeight: boolean;
}

export interface FloatingStackResizeRollback {
  groupIds: GroupId[];
  stackWeights: Record<GroupId, number> | undefined;
  restoreAutoHeight: boolean;
}

export interface FloatingStackResizeSession {
  applyDelta(deltaPx: number): FloatingStackResizeUpdate | null;
  rollback(): FloatingStackResizeRollback;
}

/**
 * Capture the immutable start of one floating-stack divider gesture.
 *
 * Auto-height is pinned only after a delta actually changes the computed cell
 * sizes. A cancelled gesture can therefore restore both the original weights
 * and the absence of an explicit height without relying on React render timing.
 */
export function createFloatingStackResizeSession({
  stack,
  weights,
  stackWeights,
  collapsed,
  containerPx,
  dividerIndex,
  minCell,
  fixedHeight,
}: {
  stack: readonly GroupId[];
  weights: readonly number[];
  stackWeights?: Readonly<Record<GroupId, number>>;
  collapsed: readonly boolean[];
  containerPx: number;
  dividerIndex: number;
  minCell: number;
  fixedHeight: boolean;
}): FloatingStackResizeSession {
  const startStack = [...stack];
  const startWeights = [...weights];
  const startCollapsed = [...collapsed];
  const resize = (deltaPx: number) =>
    cascadeResize({
      weights: startWeights,
      collapsed: startCollapsed,
      containerPx,
      dividerIndex,
      deltaPx,
      minCell,
      maxCell: Infinity,
    });
  const baseline = weightedCellSizes(startWeights, startCollapsed, containerPx);
  let originalStackWeights: Record<GroupId, number> | undefined;
  if (stackWeights === undefined) {
    originalStackWeights = undefined;
  } else {
    originalStackWeights = emptyRecord();
    for (const groupId of startStack) {
      if (Object.prototype.hasOwnProperty.call(stackWeights, groupId)) {
        originalStackWeights[groupId] = stackWeights[groupId];
      }
    }
  }

  let appliedResize = false;
  let pinnedAutoHeight = false;

  return {
    applyDelta(deltaPx) {
      const next = resize(deltaPx);
      if (baseline === null || next === null) return null;
      const changesSize = next.some(
        (size, index) => Math.abs(size - baseline[index]) > SIZE_EPSILON_PX,
      );
      if (!changesSize && !appliedResize) return null;
      if (changesSize) appliedResize = true;

      const pinAutoHeight = changesSize && !fixedHeight && !pinnedAutoHeight;
      if (pinAutoHeight) pinnedAutoHeight = true;

      const nextWeights = emptyRecord<number>();
      startStack.forEach((groupId, index) => {
        if (!startCollapsed[index]) nextWeights[groupId] = next[index];
      });
      return { weights: nextWeights, pinAutoHeight };
    },

    rollback() {
      return {
        groupIds: [...startStack],
        stackWeights:
          originalStackWeights === undefined
            ? undefined
            : cloneRecord(originalStackWeights),
        restoreAutoHeight: pinnedAutoHeight,
      };
    },
  };
}
