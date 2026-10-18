import { decode } from "@msgpack/msgpack";

import type { Message } from "./WebsocketMessages";

/** Bytes before the compressed payload: its decompressed size as a
 * little-endian uint64. */
export const HYBRID_HEADER_BYTES = 8;

export interface HybridZstdDecoder {
  decode(data: Uint8Array, decompressedSize: number): Uint8Array;
}

/** Decode one server-to-browser frame: a size header, then a zstd frame of
 * the MessagePack envelope `{messages, timestampSec}`. */
export function decodeHybridMessage(
  buffer: ArrayBuffer,
  zstdDecoder: HybridZstdDecoder,
): Message[] {
  const decompressedSize = Number(new DataView(buffer).getBigUint64(0, true));
  const decompressed = zstdDecoder.decode(
    new Uint8Array(buffer, HYBRID_HEADER_BYTES),
    decompressedSize,
  );
  return (decode(decompressed) as { messages: Message[] }).messages;
}
