import { describe, expect, it, vi } from "vitest";

import {
  createOwnedImageObjectUrl,
  inspectEncodedImage,
  inspectImageBlob,
  inspectImageDataUrl,
  LatestBlobImageInspector,
  MAX_IMAGE_DIMENSION,
  MAX_IMAGE_HEADER_BYTES,
  MAX_IMAGE_PIXELS,
  matchingImageObjectUrl,
  matchingImagePreparationFailure,
} from "./imageSafety";

function u16be(value: number): number[] {
  return [(value >>> 8) & 0xff, value & 0xff];
}

function u16le(value: number): number[] {
  return [value & 0xff, (value >>> 8) & 0xff];
}

function u24le(value: number): number[] {
  return [value & 0xff, (value >>> 8) & 0xff, (value >>> 16) & 0xff];
}

function u32be(value: number): number[] {
  return [
    Math.floor(value / 16_777_216) & 0xff,
    (value >>> 16) & 0xff,
    (value >>> 8) & 0xff,
    value & 0xff,
  ];
}

function u32le(value: number): number[] {
  return [
    value & 0xff,
    (value >>> 8) & 0xff,
    (value >>> 16) & 0xff,
    Math.floor(value / 16_777_216) & 0xff,
  ];
}

function chunk(type: string, payload: readonly number[]): number[] {
  return [
    ...u32be(payload.length),
    ...Array.from(type, (character) => character.charCodeAt(0)),
    ...payload,
    0,
    0,
    0,
    0,
  ];
}

function png(
  width: number,
  height: number,
  extraChunks: readonly number[][] = [],
): Uint8Array {
  return Uint8Array.from([
    0x89,
    0x50,
    0x4e,
    0x47,
    0x0d,
    0x0a,
    0x1a,
    0x0a,
    ...chunk("IHDR", [...u32be(width), ...u32be(height), 8, 6, 0, 0, 0]),
    ...extraChunks.flat(),
    ...chunk("IDAT", [0]),
    ...chunk("IEND", []),
  ]);
}

function jpeg(width: number, height: number): Uint8Array {
  return Uint8Array.from([
    0xff,
    0xd8,
    0xff,
    0xc0,
    0,
    11,
    8,
    ...u16be(height),
    ...u16be(width),
    1,
    1,
    0x11,
    0,
  ]);
}

function gif(width: number, height: number, frames = 1): Uint8Array {
  const descriptor = [
    0x2c,
    0,
    0,
    0,
    0,
    ...u16le(width),
    ...u16le(height),
    0,
    2,
    1,
    0,
    0,
  ];
  return Uint8Array.from([
    ...Array.from("GIF89a", (character) => character.charCodeAt(0)),
    ...u16le(width),
    ...u16le(height),
    0,
    0,
    0,
    ...Array.from({ length: frames }, () => descriptor).flat(),
    0x3b,
  ]);
}

function webpLosslessPayload(width: number, height: number): number[] {
  const packed = (width - 1) | ((height - 1) << 14);
  return [0x2f, ...u32le(packed >>> 0)];
}

function webpChunks(
  chunks: readonly [string, readonly number[]][],
): Uint8Array {
  const body: number[] = [];
  for (const [type, payload] of chunks) {
    body.push(
      ...Array.from(type, (character) => character.charCodeAt(0)),
      ...u32le(payload.length),
      ...payload,
    );
    if (payload.length % 2 !== 0) body.push(0);
  }
  return Uint8Array.from([
    ...Array.from("RIFF", (character) => character.charCodeAt(0)),
    ...u32le(4 + body.length),
    ...Array.from("WEBP", (character) => character.charCodeAt(0)),
    ...body,
  ]);
}

function webp(width: number, height: number): Uint8Array {
  return webpChunks([["VP8L", webpLosslessPayload(width, height)]]);
}

function blob(data: Uint8Array): Blob {
  return new Blob([data.slice().buffer as ArrayBuffer]);
}

describe("inspectEncodedImage", () => {
  it.each([
    ["PNG", png(640, 360), "image/png"],
    ["JPEG", jpeg(640, 360), "image/jpeg"],
    ["GIF", gif(640, 360), "image/gif"],
    ["WebP", webp(640, 360), "image/webp"],
  ])("accepts one static %s raster", (_name, data, mimeType) => {
    expect(inspectEncodedImage(data, mimeType)).toMatchObject({
      ok: true,
      size: { width: 640, height: 360 },
    });
  });

  it("enforces exact dimension and decoded-pixel boundaries", () => {
    expect(
      inspectEncodedImage(
        png(MAX_IMAGE_DIMENSION, MAX_IMAGE_PIXELS / MAX_IMAGE_DIMENSION),
      ).ok,
    ).toBe(true);
    expect(inspectEncodedImage(png(MAX_IMAGE_DIMENSION + 1, 1)).ok).toBe(false);
    expect(
      inspectEncodedImage(
        png(MAX_IMAGE_DIMENSION, MAX_IMAGE_PIXELS / MAX_IMAGE_DIMENSION + 1),
      ).ok,
    ).toBe(false);
  });

  it("rejects truncation, MIME confusion, and unknown image formats", () => {
    expect(inspectEncodedImage(png(1, 1).slice(0, 30)).ok).toBe(false);
    expect(inspectEncodedImage(png(1, 1), "image/jpeg").ok).toBe(false);
    expect(inspectEncodedImage(Uint8Array.of(1, 2, 3)).ok).toBe(false);
  });

  it.each([
    ["PNG", png(1, 1), "image/png"],
    ["GIF", gif(1, 1), "image/gif"],
    ["WebP", webp(1, 1), "image/webp"],
  ])(
    "rejects trailing bytes after a complete %s container",
    (_name, data, mime) => {
      const withTrailingByte = new Uint8Array(data.length + 1);
      withTrailingByte.set(data);
      expect(inspectEncodedImage(withTrailingByte, mime).ok).toBe(false);
    },
  );

  it("rejects a short forged JPEG frame segment", () => {
    const forged = Uint8Array.from([
      0xff,
      0xd8,
      0xff,
      0xc0,
      0,
      2,
      8,
      0,
      1,
      0,
      1,
      1,
      ...jpeg(MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION).slice(2),
    ]);
    expect(inspectEncodedImage(forged, "image/jpeg").ok).toBe(false);
  });

  it("rejects APNG, multi-frame GIF, and animated WebP", () => {
    expect(
      inspectEncodedImage(png(1, 1, [chunk("acTL", [0, 0, 0, 2, 0, 0, 0, 0])]))
        .ok,
    ).toBe(false);
    expect(inspectEncodedImage(gif(1, 1, 2)).ok).toBe(false);
    const animated = webpChunks([
      ["VP8X", [0x02, 0, 0, 0, ...u24le(0), ...u24le(0)]],
      ["ANIM", [0, 0, 0, 0, 0, 0]],
      ["VP8L", webpLosslessPayload(1, 1)],
    ]);
    expect(inspectEncodedImage(animated).ok).toBe(false);
  });

  it("requires an extended WebP canvas to match its sole payload", () => {
    const extended = (canvasWidth: number, payloadWidth: number) =>
      webpChunks([
        ["VP8X", [0, 0, 0, 0, ...u24le(canvasWidth - 1), ...u24le(0)]],
        ["VP8L", webpLosslessPayload(payloadWidth, 1)],
      ]);
    expect(inspectEncodedImage(extended(1, 1)).ok).toBe(true);
    expect(inspectEncodedImage(extended(1, MAX_IMAGE_DIMENSION + 1)).ok).toBe(
      false,
    );
  });

  it("allows bounded short ancillary WebP chunks", () => {
    const withShortChunk = webpChunks([
      ["VP8L", webpLosslessPayload(1, 1)],
      ["XMP ", []],
    ]);
    expect(inspectEncodedImage(withShortChunk).ok).toBe(true);
  });

  it("rejects a non-header leading WebP chunk and malformed VP8X length", () => {
    expect(
      inspectEncodedImage(
        webpChunks([
          ["XMP ", []],
          ["VP8L", webpLosslessPayload(1, 1)],
        ]),
      ).ok,
    ).toBe(false);
    expect(
      inspectEncodedImage(
        webpChunks([
          ["VP8X", [0, 0, 0, 0, ...u24le(0), ...u24le(0), 0]],
          ["VP8L", webpLosslessPayload(1, 1)],
        ]),
      ).ok,
    ).toBe(false);
  });

  it("validates bounded base64 data images before returning admission", () => {
    let binary = "";
    for (const byte of png(2, 3)) binary += String.fromCharCode(byte);
    const source = `data:image/png;base64,${btoa(binary)}`;
    expect(inspectImageDataUrl(source)).toMatchObject({
      ok: true,
      size: { width: 2, height: 3 },
    });
    expect(inspectImageDataUrl("data:image/png;base64,AAAA").ok).toBe(false);
  });
});

it("never reuses a valid image URL across byte or MIME generations", () => {
  const first = png(1, 1);
  const replacement = png(1, 1);
  const owned = { data: first, mimeType: "image/png", url: "blob:first" };
  expect(matchingImageObjectUrl(owned, first, "image/png")).toBe("blob:first");
  expect(matchingImageObjectUrl(owned, replacement, "image/png")).toBeNull();
  expect(matchingImageObjectUrl(owned, first, "image/jpeg")).toBeNull();
  expect(matchingImageObjectUrl(owned, null, "image/png")).toBeNull();
});

it("never exposes a URL preparation failure under replacement image props", () => {
  const first = png(1, 1);
  const replacement = png(1, 1);
  const failure = { ok: false as const, reason: "failed" };
  const owned = { data: first, mimeType: "image/png", failure };
  expect(matchingImagePreparationFailure(owned, first, "image/png")).toBe(
    failure,
  );
  expect(
    matchingImagePreparationFailure(owned, replacement, "image/png"),
  ).toBeNull();
  expect(
    matchingImagePreparationFailure(owned, first, "image/jpeg"),
  ).toBeNull();
});

it("contains object-URL creation failures as a downloadable image status", () => {
  const failure = new Error("object URLs unavailable");
  const create = vi.spyOn(URL, "createObjectURL").mockImplementation(() => {
    throw failure;
  });
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    expect(
      createOwnedImageObjectUrl(png(1, 1).slice(), "image/png"),
    ).toMatchObject({
      ok: false,
      reason: expect.stringContaining("still available to download"),
    });
    expect(log).toHaveBeenCalledWith(
      "Could not prepare an admitted image for display:",
      failure,
    );
  } finally {
    create.mockRestore();
    log.mockRestore();
  }
});

describe("inspectImageBlob", () => {
  it("uses the same static-format and WebP agreement policy", async () => {
    expect(await inspectImageBlob(blob(gif(1, 1)), "image/gif")).toMatchObject({
      ok: true,
    });
    expect(
      await inspectImageBlob(blob(gif(1, 1, 2)), "image/gif"),
    ).toMatchObject({ ok: false });
    const mismatch = webpChunks([
      ["VP8X", [0, 0, 0, 0, ...u24le(0), ...u24le(0)]],
      ["VP8L", webpLosslessPayload(2, 1)],
    ]);
    expect(await inspectImageBlob(blob(mismatch), "image/webp")).toMatchObject({
      ok: false,
    });
    const leadingAncillary = webpChunks([
      ["XMP ", []],
      ["VP8L", webpLosslessPayload(1, 1)],
    ]);
    const malformedExtended = webpChunks([
      ["VP8X", [0, 0, 0, 0, ...u24le(0), ...u24le(0), 0]],
      ["VP8L", webpLosslessPayload(1, 1)],
    ]);
    for (const invalid of [leadingAncillary, malformedExtended]) {
      expect(await inspectImageBlob(blob(invalid), "image/webp")).toMatchObject(
        { ok: false },
      );
    }
  });

  it.each([
    ["PNG", png(1, 1), "image/png"],
    ["GIF", gif(1, 1), "image/gif"],
    ["WebP", webp(1, 1), "image/webp"],
  ])(
    "rejects trailing bytes after a complete %s Blob container",
    async (_name, data, mime) => {
      expect(
        await inspectImageBlob(
          new Blob([
            data.slice().buffer as ArrayBuffer,
            Uint8Array.of(0).buffer,
          ]),
          mime,
        ),
      ).toMatchObject({ ok: false });
    },
  );

  it("rejects a short forged JPEG frame segment in a Blob", async () => {
    const forged = Uint8Array.from([
      0xff,
      0xd8,
      0xff,
      0xc0,
      0,
      2,
      8,
      0,
      1,
      0,
      1,
      1,
      ...jpeg(MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION).slice(2),
    ]);
    expect(await inspectImageBlob(blob(forged), "image/jpeg")).toMatchObject({
      ok: false,
    });
  });

  it("rejects JPEG frames hidden past the metadata scan budget", async () => {
    const parts: BlobPart[] = [Uint8Array.of(0xff, 0xd8)];
    let bytes = 2;
    while (bytes <= MAX_IMAGE_HEADER_BYTES) {
      const segment = new Uint8Array(65_535 + 2);
      segment[0] = 0xff;
      segment[1] = 0xe1;
      segment[2] = 0xff;
      segment[3] = 0xff;
      parts.push(segment.buffer as ArrayBuffer);
      bytes += segment.length;
    }
    parts.push(jpeg(1, 1).slice(2).buffer as ArrayBuffer);
    expect(await inspectImageBlob(new Blob(parts), "image/jpeg")).toMatchObject(
      { ok: false },
    );
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}

function delayedBlob(
  data: Uint8Array,
  ready: Promise<void>,
  read: () => void,
): Blob {
  return {
    size: data.length,
    slice: () => ({
      arrayBuffer: async () => {
        read();
        await ready;
        return data.slice().buffer;
      },
    }),
  } as unknown as Blob;
}

it("serializes Blob inspection and publishes only the latest generation", async () => {
  const inspector = new LatestBlobImageInspector();
  const firstReady = deferred<void>();
  const lastReady = deferred<void>();
  const firstRead = vi.fn();
  const skippedRead = vi.fn();
  const lastRead = vi.fn();
  const firstResult = vi.fn();
  const skippedResult = vi.fn();
  const lastResult = vi.fn();
  inspector.request(
    delayedBlob(png(1, 1), firstReady.promise, firstRead),
    "image/png",
    firstResult,
  );
  inspector.request(
    delayedBlob(png(2, 2), Promise.resolve(), skippedRead),
    "image/png",
    skippedResult,
  );
  inspector.request(
    delayedBlob(png(3, 3), lastReady.promise, lastRead),
    "image/png",
    lastResult,
  );

  expect(firstRead).toHaveBeenCalledOnce();
  expect(skippedRead).not.toHaveBeenCalled();
  firstReady.resolve();
  await firstReady.promise;
  expect(firstResult).not.toHaveBeenCalled();
  expect(skippedRead).not.toHaveBeenCalled();
  await vi.waitFor(() => expect(lastRead).toHaveBeenCalledOnce());
  lastReady.resolve();
  await lastReady.promise;
  await vi.waitFor(() =>
    expect(lastResult).toHaveBeenCalledWith(
      expect.objectContaining({ ok: true, size: { width: 3, height: 3 } }),
    ),
  );
  expect(skippedResult).not.toHaveBeenCalled();
});
