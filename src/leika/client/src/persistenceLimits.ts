/** Browser-owned state is an untrusted input boundary.
 *
 * The limits are deliberately much larger than a useful workspace while
 * remaining small enough that parsing, validating, and recursively operating
 * on a hand-edited localStorage value cannot exhaust the tab's stack or heap.
 */
export const MAX_PERSISTED_JSON_CODE_UNITS = 1 * 1024 * 1024;
export const MAX_LAYOUT_DEPTH = 64;
export const MAX_LAYOUT_ITEMS = 4_096;
export const MAX_LAYOUT_CHILDREN = 1_024;
export const MAX_LAYOUT_ID_CODE_UNITS = 1_024;

export function isBoundedLayoutId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= MAX_LAYOUT_ID_CODE_UNITS &&
    value !== "__proto__" &&
    value !== "prototype" &&
    value !== "constructor" &&
    !/[\uD800-\uDFFF]/.test(value)
  );
}

/** Parse a persisted value only after bounding JSON.parse's source. */
export function parseBoundedPersistedJson(serialized: string): unknown {
  if (serialized.length > MAX_PERSISTED_JSON_CODE_UNITS) return undefined;
  return JSON.parse(serialized) as unknown;
}
