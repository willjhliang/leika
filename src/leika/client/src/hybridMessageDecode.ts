import { decode } from "@msgpack/msgpack";

import {
  computeBinaryOffsets,
  isPlainRecord,
  MAX_BINARY_PLACEHOLDER_NODES,
  replaceBinaryPlaceholders,
} from "./BinaryMessageDecode";
import { type Message, validateMessage } from "./WebsocketMessages";

const MEBIBYTE = 1024 * 1024;
export const HYBRID_HEADER_BYTES = 16;
/** The metadata includes encoded images and documents, not merely control
 * messages. Keep this comfortably above the 64 MiB default preview limit. */
export const MAX_HYBRID_METADATA_BYTES = 256 * MEBIBYTE;
/** Raw ndarray panes are appended outside the compressed metadata. */
export const MAX_HYBRID_FRAME_BYTES = 512 * MEBIBYTE;
export const MAX_HYBRID_MESSAGES_PER_BATCH = 128;
export const MAX_HYBRID_BINARY_BUFFERS = 16_384;

export interface HybridZstdDecoder {
  decode(data: Uint8Array, decompressedSize: number): Uint8Array;
}

export interface DecodedHybridMessage {
  messages: Message[];
  timestampSec: number;
  buffer: ArrayBuffer;
  /** Validated decompressed metadata bytes represented by the message tree. */
  metadataBytes: number;
}

function boundedUint64(
  view: DataView,
  offset: number,
  label: string,
  maximum: number,
): number {
  const value = view.getBigUint64(offset, true);
  if (value > BigInt(maximum))
    throw new Error(`${label} exceeds the browser safety limit`);
  return Number(value);
}

function validatePayload(
  decoded: unknown,
  buffer: ArrayBuffer,
  compressedEnd: number,
  metadataBytes: number,
): DecodedHybridMessage {
  if (!isPlainRecord(decoded))
    throw new Error("decoded payload is not an object");
  const payloadKeys = Object.keys(decoded).sort();
  if (
    payloadKeys.length !== 3 ||
    payloadKeys[0] !== "binaryBufferLengths" ||
    payloadKeys[1] !== "messages" ||
    payloadKeys[2] !== "timestampSec"
  )
    throw new Error("decoded payload contains unknown or missing fields");

  const messages = decoded.messages;
  if (!Array.isArray(messages))
    throw new Error("decoded payload messages are not an array");
  if (messages.length > MAX_HYBRID_MESSAGES_PER_BATCH)
    throw new Error("decoded payload contains too many messages");
  for (const message of messages) {
    if (
      !isPlainRecord(message) ||
      typeof message.type !== "string" ||
      message.type.length === 0 ||
      message.type.length > 128
    )
      throw new Error("decoded payload contains an invalid message");
  }

  const normalizeSafeInteger = (value: unknown, label: string): unknown => {
    if (typeof value !== "bigint") return value;
    if (
      value < BigInt(Number.MIN_SAFE_INTEGER) ||
      value > BigInt(Number.MAX_SAFE_INTEGER)
    )
      throw new Error(`decoded payload contains an unsafe ${label}`);
    return Number(value);
  };

  const timestampSec = normalizeSafeInteger(
    decoded.timestampSec,
    "64-bit timestamp",
  );
  if (
    typeof timestampSec !== "number" ||
    !Number.isFinite(timestampSec) ||
    !Number.isFinite(timestampSec * 1000) ||
    timestampSec < 0
  )
    throw new Error("decoded payload timestamp is invalid");

  const bufferLengths = decoded.binaryBufferLengths;
  if (!Array.isArray(bufferLengths))
    throw new Error("decoded payload binary lengths are not an array");
  if (bufferLengths.length > MAX_HYBRID_BINARY_BUFFERS)
    throw new Error("decoded payload contains too many binary buffers");
  const validatedLengths: number[] = [];
  for (const rawLength of bufferLengths) {
    const length = normalizeSafeInteger(rawLength, "64-bit binary length");
    if (!Number.isSafeInteger(length) || (length as number) < 0)
      throw new Error("decoded payload contains an invalid binary length");
    validatedLengths.push(length as number);
  }

  const offsets = computeBinaryOffsets(
    validatedLengths,
    compressedEnd,
    buffer.byteLength,
  );
  const usedIndices = new Set<number>();
  replaceBinaryPlaceholders(
    messages,
    buffer,
    offsets,
    validatedLengths,
    usedIndices,
  );
  if (usedIndices.size !== validatedLengths.length)
    throw new Error("decoded payload contains an unreferenced binary buffer");

  const validatedMessages: Message[] = [];
  for (const message of messages) {
    validateMessage(message);
    validatedMessages.push(message);
  }

  return {
    messages: validatedMessages,
    timestampSec,
    buffer,
    metadataBytes,
  };
}

/** Decode and validate one complete server-to-browser hybrid frame.
 *
 * Every size is bounded before constructing a view or asking zstd to
 * allocate. Structural validation then precedes binary placeholder views, so
 * a corrupt or hostile peer becomes a controlled connection failure rather
 * than a worker crash or arbitrary allocation request. */
export function decodeHybridMessage(
  buffer: ArrayBuffer,
  zstdDecoder: HybridZstdDecoder,
): DecodedHybridMessage {
  if (buffer.byteLength < HYBRID_HEADER_BYTES)
    throw new Error("hybrid frame header is truncated");
  if (buffer.byteLength > MAX_HYBRID_FRAME_BYTES)
    throw new Error("hybrid frame exceeds the browser safety limit");

  const header = new DataView(buffer, 0, HYBRID_HEADER_BYTES);
  const decompressedSize = boundedUint64(
    header,
    0,
    "decompressed metadata",
    MAX_HYBRID_METADATA_BYTES,
  );
  const compressedSize = boundedUint64(
    header,
    8,
    "compressed metadata",
    MAX_HYBRID_FRAME_BYTES - HYBRID_HEADER_BYTES,
  );
  if (decompressedSize === 0 || compressedSize === 0)
    throw new Error("hybrid frame metadata is empty");
  if (compressedSize > buffer.byteLength - HYBRID_HEADER_BYTES)
    throw new Error("compressed metadata exceeds the frame");

  const compressedEnd = HYBRID_HEADER_BYTES + compressedSize;
  const compressed = new Uint8Array(
    buffer,
    HYBRID_HEADER_BYTES,
    compressedSize,
  );
  const decompressed = zstdDecoder.decode(compressed, decompressedSize);
  if (!(decompressed instanceof Uint8Array))
    throw new Error("decoder returned an invalid metadata buffer");
  if (decompressed.byteLength !== decompressedSize)
    throw new Error("decompressed metadata size does not match its header");

  const decoded = decode(decompressed, {
    // Preserve int64/uint64 exactly. The bounded traversal below normalizes
    // only values inside JavaScript's safe-integer range and rejects the rest.
    useBigInt64: true,
    // Reject hostile collection headers before the decoder allocates their
    // advertised length. The total traversal cap is enforced afterward too.
    maxArrayLength: MAX_BINARY_PLACEHOLDER_NODES,
    maxMapLength: MAX_BINARY_PLACEHOLDER_NODES,
    maxStrLength: MAX_HYBRID_METADATA_BYTES,
    maxBinLength: MAX_HYBRID_METADATA_BYTES,
    maxExtLength: MAX_HYBRID_METADATA_BYTES,
  });
  return validatePayload(decoded, buffer, compressedEnd, decompressedSize);
}
