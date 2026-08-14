/**
 * Shared decode logic for the hybrid binary message format.
 *
 * Used by the WebSocket worker to decode live messages.
 *
 * Binary arrays in the msgpack payload are replaced with tagged placeholder
 * objects: `{"__binary_index": i, "dtype": "<f4"}`. This module reconstructs
 * them as typed array views into the provided ArrayBuffer.
 */

// Dtype string (numpy convention) to TypedArray constructor mapping.
const DTYPE_CONSTRUCTORS: {
  [key: string]: {
    ctor: new (
      buffer: ArrayBuffer,
      byteOffset: number,
      length: number,
    ) => ArrayBufferView;
    bytes: number;
  };
} = {
  "|b1": { ctor: Uint8Array, bytes: 1 },
  "<f2": { ctor: Uint16Array, bytes: 2 }, // float16: stored as Uint16 (no native Float16Array)
  "<f4": { ctor: Float32Array, bytes: 4 },
  "<f8": { ctor: Float64Array, bytes: 8 },
  "|u1": { ctor: Uint8Array, bytes: 1 },
  "<u2": { ctor: Uint16Array, bytes: 2 },
  "<u4": { ctor: Uint32Array, bytes: 4 },
  "|i1": { ctor: Int8Array, bytes: 1 },
  "<i2": { ctor: Int16Array, bytes: 2 },
  "<i4": { ctor: Int32Array, bytes: 4 },
};

export const MAX_BINARY_PLACEHOLDER_DEPTH = 128;
export const MAX_BINARY_PLACEHOLDER_NODES = 500_000;

export function isPlainRecord(
  value: unknown,
): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

/**
 * Replace tagged placeholder objects in a decoded message with typed array
 * views into the binary section of an ArrayBuffer.
 *
 * @param obj - The decoded msgpack object to walk (mutated in place).
 * @param buffer - The ArrayBuffer containing the binary data.
 * @param binaryOffsets - Byte offset of each binary buffer within `buffer`.
 * @param bufferLengths - Byte length of each binary buffer.
 */
export function replaceBinaryPlaceholders(
  obj: unknown,
  buffer: ArrayBuffer,
  binaryOffsets: readonly number[],
  bufferLengths: readonly number[],
  usedIndices: Set<number>,
): unknown {
  const root: Record<string, unknown> = { value: obj };
  type WorkItem = {
    container: Record<string, unknown> | unknown[];
    key: string | number;
    depth: number;
  };
  const stack: WorkItem[] = [{ container: root, key: "value", depth: 0 }];
  let visited = 0;

  const getValue = (item: WorkItem): unknown =>
    Array.isArray(item.container)
      ? item.container[item.key as number]
      : item.container[item.key as string];
  const setValue = (item: WorkItem, value: unknown): void => {
    if (Array.isArray(item.container)) {
      item.container[item.key as number] = value;
    } else {
      Object.defineProperty(item.container, item.key, {
        configurable: true,
        enumerable: true,
        value,
        writable: true,
      });
    }
  };

  while (stack.length > 0) {
    const item = stack.pop()!;
    visited += 1;
    if (visited > MAX_BINARY_PLACEHOLDER_NODES)
      throw new Error("decoded message contains too many values");
    if (item.depth > MAX_BINARY_PLACEHOLDER_DEPTH)
      throw new Error("decoded message nesting is too deep");

    const value = getValue(item);
    if (value === null) continue;
    if (Array.isArray(value)) {
      for (let index = value.length - 1; index >= 0; index -= 1) {
        stack.push({ container: value, key: index, depth: item.depth + 1 });
      }
      continue;
    }
    if (ArrayBuffer.isView(value)) continue;
    if (typeof value === "bigint") {
      if (
        value < BigInt(Number.MIN_SAFE_INTEGER) ||
        value > BigInt(Number.MAX_SAFE_INTEGER)
      )
        throw new Error("decoded message contains an unsafe 64-bit integer");
      setValue(item, Number(value));
      continue;
    }
    if (typeof value !== "object") {
      if (
        typeof value === "string" ||
        typeof value === "number" ||
        typeof value === "boolean"
      )
        continue;
      throw new Error("decoded message contains an unsupported value");
    }
    if (!isPlainRecord(value))
      throw new Error("decoded message contains an unsupported object");

    const hasIndex = Object.hasOwn(value, "__binary_index");
    const hasDtype = Object.hasOwn(value, "dtype");
    if (hasIndex) {
      if (!hasDtype || Object.keys(value).length !== 2)
        throw new Error("binary placeholder is malformed");
      const index = value.__binary_index;
      const dtype = value.dtype;
      if (
        !Number.isSafeInteger(index) ||
        (index as number) < 0 ||
        (index as number) >= bufferLengths.length
      )
        throw new Error("binary placeholder index is out of range");
      if (typeof dtype !== "string" || dtype.length === 0 || dtype.length > 64)
        throw new Error("binary placeholder dtype is invalid");
      if (usedIndices.has(index as number))
        throw new Error("binary buffer is referenced more than once");
      usedIndices.add(index as number);

      const offset = binaryOffsets[index as number];
      const byteLength = bufferLengths[index as number];
      const dtypeInfo = DTYPE_CONSTRUCTORS[dtype];
      if (dtypeInfo === undefined)
        throw new Error("binary placeholder dtype is unsupported");
      if (byteLength % dtypeInfo.bytes !== 0 || offset % dtypeInfo.bytes !== 0)
        throw new Error("binary buffer does not match its dtype");
      setValue(
        item,
        new dtypeInfo.ctor(buffer, offset, byteLength / dtypeInfo.bytes),
      );
      continue;
    }

    const keys = Object.keys(value);
    for (let index = keys.length - 1; index >= 0; index -= 1) {
      stack.push({
        container: value,
        key: keys[index],
        depth: item.depth + 1,
      });
    }
  }

  return root.value;
}

/**
 * Compute binary buffer offsets from their lengths, starting from a base offset,
 * respecting 8-byte alignment.
 */
export function computeBinaryOffsets(
  bufferLengths: readonly number[],
  baseOffset: number,
  frameByteLength: number,
): number[] {
  if (
    !Number.isSafeInteger(baseOffset) ||
    baseOffset < 0 ||
    !Number.isSafeInteger(frameByteLength) ||
    frameByteLength < baseOffset
  )
    throw new Error("binary section bounds are invalid");

  const offsets: number[] = [];
  let offset = baseOffset;
  for (const length of bufferLengths) {
    if (!Number.isSafeInteger(length) || length < 0)
      throw new Error("binary buffer length is invalid");
    const padding = (8 - (offset % 8)) % 8;
    if (padding > frameByteLength - offset)
      throw new Error("binary alignment exceeds the frame");
    offset += padding;
    offsets.push(offset);
    if (length > frameByteLength - offset)
      throw new Error("binary buffer exceeds the frame");
    offset += length;
  }
  if (offset !== frameByteLength)
    throw new Error("binary section does not consume the complete frame");
  return offsets;
}
