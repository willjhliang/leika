import { decode } from "@msgpack/msgpack";

import type { Message } from "./WebsocketMessages";

/** Bytes before the compressed payload: its decompressed size as a
 * little-endian uint64. */
export const HYBRID_HEADER_BYTES = 8;
/** Largest frame the worker's receive queue admits. */
export const MAX_HYBRID_FRAME_BYTES = 512 * 1024 * 1024;

export interface HybridZstdDecoder {
  /** Return independently owned bytes, not a view into reusable WASM memory.
   * The worker transfers this buffer after decoding it. */
  decode(data: Uint8Array, decompressedSize: number): Uint8Array;
}

export interface DecodedHybridMessage {
  messages: Message[];
  timestampSec: number;
  /** Binary values are views into the decompressed payload, which crosses
   * the worker boundary without copying. */
  transferables: ArrayBuffer[];
  /** Decompressed payload bytes represented by the messages. */
  metadataBytes: number;
}

/** Decode one server-to-browser frame: a size header, then a zstd frame of
 * the MessagePack envelope `{messages, timestampSec}`. */
export function decodeHybridMessage(
  buffer: ArrayBuffer,
  zstdDecoder: HybridZstdDecoder,
): DecodedHybridMessage {
  const decompressedSize = Number(new DataView(buffer).getBigUint64(0, true));
  const decompressed = zstdDecoder.decode(
    new Uint8Array(buffer, HYBRID_HEADER_BYTES),
    decompressedSize,
  );
  const { messages, timestampSec } = decode(decompressed) as {
    messages: Message[];
    timestampSec: number;
  };
  return {
    messages,
    timestampSec,
    transferables: [decompressed.buffer as ArrayBuffer],
    metadataBytes: decompressedSize,
  };
}
