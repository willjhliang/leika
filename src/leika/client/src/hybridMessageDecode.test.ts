import { encode } from "@msgpack/msgpack";
import { describe, expect, it } from "vitest";

import {
  decodeHybridMessage,
  HYBRID_HEADER_BYTES,
  type HybridZstdDecoder,
} from "./hybridMessageDecode";

// Like zstddec, return fresh owned bytes rather than a view of the input.
const copyingDecoder: HybridZstdDecoder = {
  decode: (data) => data.slice(),
};

function frame(envelope: unknown): ArrayBuffer {
  const payload = encode(envelope);
  const buffer = new ArrayBuffer(HYBRID_HEADER_BYTES + payload.byteLength);
  new DataView(buffer).setBigUint64(0, BigInt(payload.byteLength), true);
  new Uint8Array(buffer).set(payload, HYBRID_HEADER_BYTES);
  return buffer;
}

const update = {
  type: "GuiUpdateMessage",
  uuid: "test",
  updates: { value: 1, inline: new Uint8Array([9, 8]) },
};

describe("decodeHybridMessage", () => {
  it("decodes the messages and timestamp of one frame", () => {
    const buffer = frame({ messages: [update], timestampSec: 12.5 });
    const result = decodeHybridMessage(buffer, copyingDecoder);
    expect(result.messages).toEqual([update]);
    expect(result.timestampSec).toBe(12.5);
    expect(result.metadataBytes).toBe(buffer.byteLength - HYBRID_HEADER_BYTES);
  });

  it("hands the decoder only the compressed bytes and their decompressed size", () => {
    const buffer = frame({ messages: [], timestampSec: 0 });
    const calls: [number, number][] = [];
    decodeHybridMessage(buffer, {
      decode: (data, size) => {
        calls.push([data.byteLength, size]);
        return data.slice();
      },
    });
    const size = buffer.byteLength - HYBRID_HEADER_BYTES;
    expect(calls).toEqual([[size, size]]);
  });

  it("moves binary values with their payload instead of cloning them", () => {
    const result = decodeHybridMessage(
      frame({ messages: [update], timestampSec: 0 }),
      copyingDecoder,
    );
    const moved = structuredClone(result.messages, {
      transfer: result.transferables,
    });
    expect(
      result.transferables.every((buffer) => buffer.byteLength === 0),
    ).toBe(true);
    expect(moved).toEqual([update]);
  });
});
