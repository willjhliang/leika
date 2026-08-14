import { encode } from "@msgpack/msgpack";
import { describe, expect, it, vi } from "vitest";

import {
  MAX_BINARY_PLACEHOLDER_DEPTH,
  MAX_BINARY_PLACEHOLDER_NODES,
  replaceBinaryPlaceholders,
} from "./BinaryMessageDecode";
import {
  decodeHybridMessage,
  HYBRID_HEADER_BYTES,
  MAX_HYBRID_BINARY_BUFFERS,
  MAX_HYBRID_MESSAGES_PER_BATCH,
  type HybridZstdDecoder,
} from "./hybridMessageDecode";

const identityDecoder: HybridZstdDecoder = {
  decode: (data) => data,
};

function frame(
  decoded: unknown,
  binaryBuffers: Uint8Array[] = [],
): ArrayBuffer {
  const metadata = encode(decoded, {
    maxDepth: MAX_BINARY_PLACEHOLDER_DEPTH + 16,
  });
  let size = HYBRID_HEADER_BYTES + metadata.byteLength;
  for (const binary of binaryBuffers) {
    size += (8 - (size % 8)) % 8;
    size += binary.byteLength;
  }

  const buffer = new ArrayBuffer(size);
  const header = new DataView(buffer);
  header.setBigUint64(0, BigInt(metadata.byteLength), true);
  header.setBigUint64(8, BigInt(metadata.byteLength), true);
  const bytes = new Uint8Array(buffer);
  bytes.set(metadata, HYBRID_HEADER_BYTES);
  let offset = HYBRID_HEADER_BYTES + metadata.byteLength;
  for (const binary of binaryBuffers) {
    offset += (8 - (offset % 8)) % 8;
    bytes.set(binary, offset);
    offset += binary.byteLength;
  }
  return buffer;
}

function rawFrame(metadata: Uint8Array): ArrayBuffer {
  const buffer = new ArrayBuffer(HYBRID_HEADER_BYTES + metadata.byteLength);
  const header = new DataView(buffer);
  header.setBigUint64(0, BigInt(metadata.byteLength), true);
  header.setBigUint64(8, BigInt(metadata.byteLength), true);
  new Uint8Array(buffer).set(metadata, HYBRID_HEADER_BYTES);
  return buffer;
}

function bigintFrame(decoded: unknown): ArrayBuffer {
  return rawFrame(encode(decoded, { useBigInt64: true }));
}

function payload(
  overrides: Partial<{
    messages: unknown;
    timestampSec: unknown;
    binaryBufferLengths: unknown;
  }> = {},
) {
  return {
    messages: [testMessage()],
    timestampSec: 123,
    binaryBufferLengths: [],
    ...overrides,
  };
}

function testMessage(updates: Record<string, unknown> = {}) {
  return { type: "GuiUpdateMessage", uuid: "test", updates };
}

describe("decodeHybridMessage", () => {
  it("reconstructs validated aligned typed-array placeholders", () => {
    const floats = new Float32Array([1.5, 2.5]);
    const binary = new Uint8Array(
      floats.buffer,
      floats.byteOffset,
      floats.byteLength,
    );
    const buffer = frame(
      payload({
        messages: [
          testMessage({
            points: { __binary_index: 0, dtype: "<f4" },
          }),
        ],
        binaryBufferLengths: [binary.byteLength],
      }),
      [binary],
    );

    const result = decodeHybridMessage(buffer, identityDecoder);
    const message = result.messages[0] as unknown as {
      updates: { points: Float32Array };
    };
    expect(message.updates.points).toBeInstanceOf(Float32Array);
    expect([...message.updates.points]).toEqual([1.5, 2.5]);
    expect(message.updates.points.buffer).toBe(buffer);
    expect(result.metadataBytes).toBeGreaterThan(0);
  });

  it("preserves ordinary msgpack bytes and decodes the explicit bool dtype", () => {
    const raw = new Uint8Array([3, 2, 1]);
    const result = decodeHybridMessage(
      frame(
        payload({
          messages: [
            testMessage({
              inline: new Uint8Array([9, 8]),
              flags: { __binary_index: 0, dtype: "|b1" },
              ordinary: { dtype: "description" },
            }),
          ],
          binaryBufferLengths: [raw.byteLength],
        }),
        [raw],
      ),
      identityDecoder,
    );
    const message = result.messages[0] as unknown as {
      updates: {
        inline: Uint8Array;
        flags: Uint8Array;
        ordinary: { dtype: string };
      };
    };
    expect(message.updates.inline).toEqual(new Uint8Array([9, 8]));
    expect(message.updates.flags).toBeInstanceOf(Uint8Array);
    expect([...message.updates.flags]).toEqual([3, 2, 1]);
    expect(message.updates.flags.buffer).toBe(result.buffer);
    expect(message.updates.ordinary).toEqual({ dtype: "description" });
  });

  it.each(["|O", "|V3", ">f4", "<c8", "<i8", "<M8", "mystery"])(
    "rejects the unsupported or non-native dtype %s",
    (dtype) => {
      const raw = new Uint8Array(8);
      expect(() =>
        decodeHybridMessage(
          frame(
            payload({
              messages: [
                testMessage({
                  value: { __binary_index: 0, dtype },
                }),
              ],
              binaryBufferLengths: [raw.byteLength],
            }),
            [raw],
          ),
          identityDecoder,
        ),
      ).toThrow("dtype is unsupported");
    },
  );

  it("rejects a truncated header before calling the decoder", () => {
    const decoder = { decode: vi.fn() };
    expect(() =>
      decodeHybridMessage(new ArrayBuffer(HYBRID_HEADER_BYTES - 1), decoder),
    ).toThrow("header is truncated");
    expect(decoder.decode).not.toHaveBeenCalled();
  });

  it("rejects unsafe uint64 allocation requests before calling the decoder", () => {
    const buffer = new ArrayBuffer(HYBRID_HEADER_BYTES + 1);
    const header = new DataView(buffer);
    header.setBigUint64(0, 0xffff_ffff_ffff_ffffn, true);
    header.setBigUint64(8, 1n, true);
    const decoder = { decode: vi.fn() };

    expect(() => decodeHybridMessage(buffer, decoder)).toThrow(
      "decompressed metadata exceeds",
    );
    expect(decoder.decode).not.toHaveBeenCalled();
  });

  it("rejects compressed slices outside the received frame", () => {
    const buffer = new ArrayBuffer(HYBRID_HEADER_BYTES + 1);
    const header = new DataView(buffer);
    header.setBigUint64(0, 1n, true);
    header.setBigUint64(8, 2n, true);
    const decoder = { decode: vi.fn() };

    expect(() => decodeHybridMessage(buffer, decoder)).toThrow(
      "compressed metadata exceeds the frame",
    );
    expect(decoder.decode).not.toHaveBeenCalled();
  });

  it("requires zstd to return exactly the declared allocation", () => {
    const buffer = frame(payload());
    expect(() =>
      decodeHybridMessage(buffer, { decode: () => new Uint8Array(1) }),
    ).toThrow("decompressed metadata size does not match");
  });

  it.each([
    ["top-level array", []],
    ["unknown top-level field", { ...payload(), ignored: { large: true } }],
    ["non-array messages", payload({ messages: {} })],
    ["message without type", payload({ messages: [{}] })],
    ["invalid timestamp", payload({ timestampSec: "soon" })],
    ["non-array binary lengths", payload({ binaryBufferLengths: 0 })],
    ["negative binary length", payload({ binaryBufferLengths: [-1] })],
    ["fractional binary length", payload({ binaryBufferLengths: [1.5] })],
  ])("rejects a structurally invalid payload: %s", (_label, decoded) => {
    expect(() =>
      decodeHybridMessage(frame(decoded), identityDecoder),
    ).toThrow();
  });

  it("rejects an unknown discriminant and malformed known fields", () => {
    expect(() =>
      decodeHybridMessage(
        frame(payload({ messages: [{ type: "FutureMessage", value: 1 }] })),
        identityDecoder,
      ),
    ).toThrow("unsupported message type");

    expect(() =>
      decodeHybridMessage(
        frame(
          payload({
            messages: [
              testMessage({ before: true }),
              {
                type: "GuiFolderMessage",
                uuid: "folder",
                container_uuid: "root",
                // Missing `order`, which stateful lifecycle handlers assume.
                props: {
                  label: "Malformed",
                  visible: true,
                  expand_by_default: false,
                },
              },
              testMessage({ after: true }),
            ],
          }),
        ),
        identityDecoder,
      ),
    ).toThrow("GuiFolderMessage does not match its protocol schema");
  });

  it("rejects dangerous or oversized wire identities before state dispatch", () => {
    const folder = (uuid: string) => ({
      type: "GuiFolderMessage",
      uuid,
      container_uuid: "root",
      props: {
        order: 0,
        label: "Folder",
        visible: true,
        expand_by_default: false,
      },
    });
    for (const uuid of [
      "",
      "__proto__",
      "constructor",
      "\ud800",
      "x".repeat(1_025),
    ]) {
      expect(() =>
        decodeHybridMessage(
          frame(payload({ messages: [folder(uuid)] })),
          identityDecoder,
        ),
      ).toThrow("does not match its protocol schema");
    }
  });

  it("rejects unexpected known-message fields and unsafe integer fields", () => {
    expect(() =>
      decodeHybridMessage(
        frame(
          payload({
            messages: [{ ...testMessage(), unexpected: true }],
          }),
        ),
        identityDecoder,
      ),
    ).toThrow("GuiUpdateMessage does not match its protocol schema");

    expect(() =>
      decodeHybridMessage(
        frame(
          payload({
            messages: [
              {
                type: "FileTransferPartAck",
                source_component_uuid: null,
                transfer_uuid: "transfer",
                transferred_bytes: Number.MAX_SAFE_INTEGER + 1,
                total_bytes: 1,
              },
            ],
          }),
        ),
        identityDecoder,
      ),
    ).toThrow("FileTransferPartAck does not match its protocol schema");
  });

  it("normalizes exact safe int64 values and rejects their unsafe neighbors", () => {
    const exact = decodeHybridMessage(
      bigintFrame(
        payload({
          messages: [
            testMessage({
              positive: BigInt(Number.MAX_SAFE_INTEGER),
              negative: BigInt(Number.MIN_SAFE_INTEGER),
            }),
          ],
        }),
      ),
      identityDecoder,
    );
    const message = exact.messages[0];
    expect(message).toMatchObject({
      type: "GuiUpdateMessage",
      updates: {
        positive: Number.MAX_SAFE_INTEGER,
        negative: Number.MIN_SAFE_INTEGER,
      },
    });

    for (const unsafe of [
      BigInt(Number.MAX_SAFE_INTEGER) + 1n,
      BigInt(Number.MIN_SAFE_INTEGER) - 1n,
    ]) {
      expect(() =>
        decodeHybridMessage(
          bigintFrame(
            payload({ messages: [testMessage({ unsafeInteger: unsafe })] }),
          ),
          identityDecoder,
        ),
      ).toThrow("unsafe 64-bit integer");
    }
  });

  it("rejects a finite timestamp whose millisecond conversion overflows", () => {
    expect(() =>
      decodeHybridMessage(
        frame(payload({ timestampSec: Number.MAX_VALUE })),
        identityDecoder,
      ),
    ).toThrow("timestamp is invalid");
    expect(
      decodeHybridMessage(
        frame(payload({ timestampSec: Number.MAX_VALUE / 1000 })),
        identityDecoder,
      ).timestampSec,
    ).toBe(Number.MAX_VALUE / 1000);
  });

  it("normalizes a safe int64 envelope timestamp and rejects an unsafe one", () => {
    expect(
      decodeHybridMessage(
        bigintFrame(payload({ timestampSec: 123n })),
        identityDecoder,
      ).timestampSec,
    ).toBe(123);
    expect(() =>
      decodeHybridMessage(
        bigintFrame(
          payload({
            timestampSec: BigInt(Number.MAX_SAFE_INTEGER) + 1n,
          }),
        ),
        identityDecoder,
      ),
    ).toThrow("unsafe 64-bit timestamp");
  });

  it("validates ordinary msgpack bytes in a declared bytes field", () => {
    const result = decodeHybridMessage(
      frame(
        payload({
          messages: [
            {
              type: "FileTransferPart",
              source_component_uuid: null,
              transfer_uuid: "transfer",
              part_index: 0,
              content: new Uint8Array([1, 2, 3]),
            },
          ],
        }),
      ),
      identityDecoder,
    );

    expect(result.messages[0]).toMatchObject({
      type: "FileTransferPart",
      content: new Uint8Array([1, 2, 3]),
    });
  });

  it("walks Any arrays above JavaScript's argument limit without spreading", () => {
    const values = new Array(200_000).fill(1);
    const result = decodeHybridMessage(
      frame(payload({ messages: [testMessage({ values })] })),
      identityDecoder,
    );

    const message = result.messages[0];
    expect(message.type).toBe("GuiUpdateMessage");
    if (message.type !== "GuiUpdateMessage")
      throw new Error("wrong message type");
    expect(message.updates.values).toHaveLength(values.length);
  });

  it("caps a decoded batch at the server window size", () => {
    const messages = Array.from(
      { length: MAX_HYBRID_MESSAGES_PER_BATCH + 1 },
      () => testMessage(),
    );
    expect(() =>
      decodeHybridMessage(frame(payload({ messages })), identityDecoder),
    ).toThrow("too many messages");
  });

  it("caps binary-buffer declarations", () => {
    const binaryBufferLengths = new Array(MAX_HYBRID_BINARY_BUFFERS + 1).fill(
      0,
    );
    expect(() =>
      decodeHybridMessage(
        frame(payload({ binaryBufferLengths })),
        identityDecoder,
      ),
    ).toThrow("too many binary buffers");
  });

  it.each([
    ["array", 0xdd],
    ["map", 0xdf],
  ])(
    "rejects an excessive MessagePack %s count before allocation",
    (_label, tag) => {
      const count = MAX_BINARY_PLACEHOLDER_NODES + 1;
      const metadata = new Uint8Array([
        tag,
        (count >>> 24) & 0xff,
        (count >>> 16) & 0xff,
        (count >>> 8) & 0xff,
        count & 0xff,
      ]);
      expect(() =>
        decodeHybridMessage(rawFrame(metadata), identityDecoder),
      ).toThrow();
    },
  );

  it("rejects truncated and trailing binary sections", () => {
    const truncated = frame(payload({ binaryBufferLengths: [4] }), []);
    expect(() => decodeHybridMessage(truncated, identityDecoder)).toThrow(
      /binary (alignment|buffer) exceeds the frame/,
    );

    const valid = frame(payload());
    const trailing = new ArrayBuffer(valid.byteLength + 1);
    new Uint8Array(trailing).set(new Uint8Array(valid));
    expect(() => decodeHybridMessage(trailing, identityDecoder)).toThrow(
      "does not consume the complete frame",
    );
  });

  it("rejects malformed, duplicate, and unreferenced placeholders", () => {
    const raw = new Uint8Array([1, 2, 3, 4]);
    const malformed = frame(
      payload({
        messages: [
          testMessage({
            value: { __binary_index: 0 },
          }),
        ],
        binaryBufferLengths: [4],
      }),
      [raw],
    );
    expect(() => decodeHybridMessage(malformed, identityDecoder)).toThrow(
      "placeholder is malformed",
    );

    const invalidIndex = frame(
      payload({
        messages: [
          testMessage({
            value: { __binary_index: 1, dtype: "|u1" },
          }),
        ],
        binaryBufferLengths: [4],
      }),
      [raw],
    );
    expect(() => decodeHybridMessage(invalidIndex, identityDecoder)).toThrow(
      "index is out of range",
    );

    const duplicate = frame(
      payload({
        messages: [
          testMessage({
            left: { __binary_index: 0, dtype: "|u1" },
            right: { __binary_index: 0, dtype: "|u1" },
          }),
        ],
        binaryBufferLengths: [4],
      }),
      [raw],
    );
    expect(() => decodeHybridMessage(duplicate, identityDecoder)).toThrow(
      "referenced more than once",
    );

    const unreferenced = frame(payload({ binaryBufferLengths: [4] }), [raw]);
    expect(() => decodeHybridMessage(unreferenced, identityDecoder)).toThrow(
      "unreferenced binary buffer",
    );
  });

  it("rejects typed buffers whose lengths cannot represent the dtype", () => {
    const raw = new Uint8Array([1, 2, 3]);
    const buffer = frame(
      payload({
        messages: [
          testMessage({
            value: { __binary_index: 0, dtype: "<f4" },
          }),
        ],
        binaryBufferLengths: [3],
      }),
      [raw],
    );
    expect(() => decodeHybridMessage(buffer, identityDecoder)).toThrow(
      "does not match its dtype",
    );
  });

  it("bounds decoded nesting depth before recursive consumers see it", () => {
    let nested: unknown = "leaf";
    for (let index = 0; index < MAX_BINARY_PLACEHOLDER_DEPTH + 1; index += 1) {
      nested = { nested };
    }
    expect(() =>
      decodeHybridMessage(
        frame(payload({ messages: [testMessage({ nested })] })),
        identityDecoder,
      ),
    ).toThrow("nesting is too deep");
  });

  it("bounds the total number of decoded values", () => {
    const values = new Array(MAX_BINARY_PLACEHOLDER_NODES).fill(0);
    expect(() =>
      decodeHybridMessage(
        frame(payload({ messages: [testMessage({ values })] })),
        identityDecoder,
      ),
    ).toThrow("too many values");
  });

  it("rejects misaligned typed-array views before constructing them", () => {
    const container = {
      value: { __binary_index: 0, dtype: "<f4" },
    };
    expect(() =>
      replaceBinaryPlaceholders(
        container,
        new ArrayBuffer(8),
        [1],
        [4],
        new Set(),
      ),
    ).toThrow("does not match its dtype");
  });
});
