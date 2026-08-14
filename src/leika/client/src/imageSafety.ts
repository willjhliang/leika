import type { MediaSize } from "./components/mediaPreviewSize";

export const MAX_IMAGE_DIMENSION = 16_384;
export const MAX_IMAGE_PIXELS = 32 * 1024 * 1024;
/** Header work is independent of the much larger downloadable file budget.
 * Four MiB accommodates ordinary EXIF/ICC metadata while making a deliberately
 * metadata-heavy JPEG a safe download-only fallback. */
export const MAX_IMAGE_HEADER_BYTES = 4 * 1024 * 1024;
export const MAX_MARKDOWN_DATA_IMAGE_CODE_UNITS = 1 * 1024 * 1024;
export const MAX_IMAGE_STRUCTURE_ITEMS = 65_536;

export const SAFE_RASTER_MIME_TYPES = [
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
] as const;
export type SafeRasterMimeType = (typeof SAFE_RASTER_MIME_TYPES)[number];
type RasterFormat = "png" | "jpeg" | "gif" | "webp";

const MIME_FROM_FORMAT: Record<RasterFormat, SafeRasterMimeType> = {
  png: "image/png",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
};
const SAFE_MIME_TYPES = new Set<string>(SAFE_RASTER_MIME_TYPES);

export interface AdmittedImage {
  ok: true;
  format: RasterFormat;
  mimeType: SafeRasterMimeType;
  size: MediaSize;
}

export interface RejectedImage {
  ok: false;
  reason: string;
}

export type ImageAdmission = AdmittedImage | RejectedImage;

export interface OwnedImageObjectUrl {
  data: Uint8Array;
  mimeType: string;
  url: string;
}

export interface OwnedImagePreparationFailure {
  data: Uint8Array;
  mimeType: string;
  failure: RejectedImage;
}

export const IMAGE_OBJECT_URL_FAILURE_MESSAGE =
  "Image preview could not be prepared. The encoded image is still available to download.";

export function createOwnedImageObjectUrl(
  data: Uint8Array<ArrayBuffer>,
  mimeType: string,
): OwnedImageObjectUrl | RejectedImage {
  try {
    return {
      data,
      mimeType,
      url: URL.createObjectURL(new Blob([data], { type: mimeType })),
    };
  } catch (error) {
    console.error("Could not prepare an admitted image for display:", error);
    return { ok: false, reason: IMAGE_OBJECT_URL_FAILURE_MESSAGE };
  }
}

/** Render an object URL only for the exact byte object and MIME that own it.
 * Effects run after paint, so clearing stale state in an effect alone leaves
 * one frame where replacement props can otherwise label old pixels. */
export function matchingImageObjectUrl(
  owned: OwnedImageObjectUrl | null,
  data: Uint8Array | null,
  mimeType: string,
): string | null {
  return owned?.data === data && owned.mimeType === mimeType ? owned.url : null;
}

export function matchingImagePreparationFailure(
  owned: OwnedImagePreparationFailure | null,
  data: Uint8Array | null,
  mimeType: string,
): RejectedImage | null {
  return owned?.data === data && owned.mimeType === mimeType
    ? owned.failure
    : null;
}

export const MALFORMED_IMAGE_MESSAGE =
  "Image preview is unavailable because its raster header is malformed or unsupported.";

export function normalizedSafeRasterMimeType(
  mimeType: string,
): SafeRasterMimeType | null {
  const normalized = mimeType.split(";", 1)[0].trim().toLowerCase();
  return SAFE_MIME_TYPES.has(normalized)
    ? (normalized as SafeRasterMimeType)
    : null;
}

function u16be(data: Uint8Array, at: number): number | null {
  if (at < 0 || at + 2 > data.length) return null;
  return data[at] * 256 + data[at + 1];
}

function u16le(data: Uint8Array, at: number): number | null {
  if (at < 0 || at + 2 > data.length) return null;
  return data[at] + data[at + 1] * 256;
}

function u24le(data: Uint8Array, at: number): number | null {
  if (at < 0 || at + 3 > data.length) return null;
  return data[at] + data[at + 1] * 256 + data[at + 2] * 65_536;
}

function u32be(data: Uint8Array, at: number): number | null {
  if (at < 0 || at + 4 > data.length) return null;
  return (
    data[at] * 16_777_216 +
    data[at + 1] * 65_536 +
    data[at + 2] * 256 +
    data[at + 3]
  );
}

function u32le(data: Uint8Array, at: number): number | null {
  if (at < 0 || at + 4 > data.length) return null;
  return (
    data[at] +
    data[at + 1] * 256 +
    data[at + 2] * 65_536 +
    data[at + 3] * 16_777_216
  );
}

function bytesEqual(
  data: Uint8Array,
  at: number,
  expected: readonly number[],
): boolean {
  if (at < 0 || at + expected.length > data.length) return false;
  for (let index = 0; index < expected.length; index += 1) {
    if (data[at + index] !== expected[index]) return false;
  }
  return true;
}

interface RawImageSize extends MediaSize {
  format: RasterFormat;
}

const JPEG_FRAME_MARKERS = new Set([
  0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf,
]);

function jpegSize(data: Uint8Array): RawImageSize | null {
  let at = 2;
  const limit = Math.min(data.length, MAX_IMAGE_HEADER_BYTES);
  while (at + 3 < limit) {
    if (data[at] !== 0xff) return null;
    const marker = data[at + 1];
    at += 2;
    if (marker === 0xff) {
      at -= 1;
      continue;
    }
    if (
      marker === 0x01 ||
      marker === 0xd8 ||
      marker === 0xd9 ||
      (marker >= 0xd0 && marker <= 0xd7)
    ) {
      continue;
    }
    if (marker === 0xda) return null;
    const length = u16be(data, at);
    if (length === null || length < 2 || at + length > limit) return null;
    if (JPEG_FRAME_MARKERS.has(marker)) {
      if (length < 11) return null;
      const componentCount = data[at + 7];
      if (componentCount === 0 || length !== 8 + 3 * componentCount)
        return null;
      const height = u16be(data, at + 3);
      const width = u16be(data, at + 5);
      return width === null || height === null || width === 0 || height === 0
        ? null
        : { format: "jpeg", width, height };
    }
    at += length;
  }
  return null;
}

function pngSize(data: Uint8Array): RawImageSize | null {
  if (!bytesEqual(data, 0, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))
    return null;
  let at = 8;
  let size: RawImageSize | null = null;
  let hasImageData = false;
  for (
    let chunkCount = 0;
    chunkCount < MAX_IMAGE_STRUCTURE_ITEMS;
    chunkCount += 1
  ) {
    const length = u32be(data, at);
    if (length === null || at + 12 + length > data.length) return null;
    const type = String.fromCharCode(
      data[at + 4],
      data[at + 5],
      data[at + 6],
      data[at + 7],
    );
    if (type === "acTL" || type === "fcTL" || type === "fdAT") return null;
    if (type === "IHDR") {
      if (at !== 8 || length !== 13 || size !== null) return null;
      const width = u32be(data, at + 8);
      const height = u32be(data, at + 12);
      if (width === null || height === null || width === 0 || height === 0)
        return null;
      size = { format: "png", width, height };
    }
    if (type === "IDAT") hasImageData = true;
    at += 12 + length;
    if (type === "IEND")
      return length === 0 && at === data.length && size !== null && hasImageData
        ? size
        : null;
  }
  return null;
}

function skipGifSubBlocks(data: Uint8Array, start: number): number | null {
  let at = start;
  for (let count = 0; count < MAX_IMAGE_STRUCTURE_ITEMS; count += 1) {
    if (at >= data.length) return null;
    const length = data[at];
    at += 1;
    if (length === 0) return at;
    if (at + length > data.length) return null;
    at += length;
  }
  return null;
}

function gifSize(data: Uint8Array): RawImageSize | null {
  if (
    !bytesEqual(data, 0, [0x47, 0x49, 0x46, 0x38, 0x37, 0x61]) &&
    !bytesEqual(data, 0, [0x47, 0x49, 0x46, 0x38, 0x39, 0x61])
  )
    return null;
  const width = u16le(data, 6);
  const height = u16le(data, 8);
  if (
    width === null ||
    height === null ||
    width === 0 ||
    height === 0 ||
    data.length < 13
  )
    return null;
  let at = 13;
  if ((data[10] & 0x80) !== 0) at += 3 * 2 ** ((data[10] & 0x07) + 1);
  let frameCount = 0;
  for (
    let itemCount = 0;
    itemCount < MAX_IMAGE_STRUCTURE_ITEMS;
    itemCount += 1
  ) {
    if (at >= data.length) return null;
    const introducer = data[at];
    at += 1;
    if (introducer === 0x3b) {
      return frameCount === 1 && at === data.length
        ? { format: "gif", width, height }
        : null;
    }
    if (introducer === 0x21) {
      if (at >= data.length) return null;
      at += 1; // Extension label; the rest is a sub-block sequence.
      const next = skipGifSubBlocks(data, at);
      if (next === null) return null;
      at = next;
      continue;
    }
    if (introducer !== 0x2c || at + 9 > data.length) return null;
    frameCount += 1;
    if (frameCount > 1) return null;
    const left = u16le(data, at);
    const top = u16le(data, at + 2);
    const frameWidth = u16le(data, at + 4);
    const frameHeight = u16le(data, at + 6);
    if (
      left === null ||
      top === null ||
      frameWidth === null ||
      frameHeight === null ||
      frameWidth === 0 ||
      frameHeight === 0 ||
      left + frameWidth > width ||
      top + frameHeight > height
    )
      return null;
    const packed = data[at + 8];
    at += 9;
    if ((packed & 0x80) !== 0) at += 3 * 2 ** ((packed & 0x07) + 1);
    if (at >= data.length) return null;
    at += 1; // LZW minimum code size.
    const next = skipGifSubBlocks(data, at);
    if (next === null) return null;
    at = next;
  }
  return null;
}

function webpPayloadSize(
  data: Uint8Array,
  typeAt: number,
  payloadAt: number,
  length: number,
): RawImageSize | null {
  if (bytesEqual(data, typeAt, [0x56, 0x50, 0x38, 0x58])) {
    if (
      length !== 10 ||
      payloadAt + 10 > data.length ||
      (data[payloadAt] & 0x02) !== 0
    )
      return null;
    const width = u24le(data, payloadAt + 4);
    const height = u24le(data, payloadAt + 7);
    return width === null || height === null
      ? null
      : { format: "webp", width: width + 1, height: height + 1 };
  }
  if (bytesEqual(data, typeAt, [0x56, 0x50, 0x38, 0x20])) {
    if (length < 10 || !bytesEqual(data, payloadAt + 3, [0x9d, 0x01, 0x2a]))
      return null;
    const rawWidth = u16le(data, payloadAt + 6);
    const rawHeight = u16le(data, payloadAt + 8);
    const width = rawWidth === null ? 0 : rawWidth & 0x3fff;
    const height = rawHeight === null ? 0 : rawHeight & 0x3fff;
    return width === 0 || height === 0
      ? null
      : { format: "webp", width, height };
  }
  if (bytesEqual(data, typeAt, [0x56, 0x50, 0x38, 0x4c])) {
    if (length < 5 || data[payloadAt] !== 0x2f) return null;
    const packed = u32le(data, payloadAt + 1);
    return packed === null
      ? null
      : {
          format: "webp",
          width: (packed & 0x3fff) + 1,
          height: ((packed >>> 14) & 0x3fff) + 1,
        };
  }
  return null;
}

function webpSize(data: Uint8Array): RawImageSize | null {
  if (
    !bytesEqual(data, 0, [0x52, 0x49, 0x46, 0x46]) ||
    !bytesEqual(data, 8, [0x57, 0x45, 0x42, 0x50])
  )
    return null;
  const riffSize = u32le(data, 4);
  if (riffSize === null || riffSize < 4 || riffSize + 8 !== data.length)
    return null;
  const end = riffSize + 8;
  let at = 12;
  let canvas: RawImageSize | null = null;
  let payloadSize: RawImageSize | null = null;
  let imagePayloads = 0;
  for (
    let chunkCount = 0;
    chunkCount < MAX_IMAGE_STRUCTURE_ITEMS;
    chunkCount += 1
  ) {
    if (at === end) {
      if (payloadSize === null || imagePayloads !== 1) return null;
      return canvas === null ||
        (canvas.width === payloadSize.width &&
          canvas.height === payloadSize.height)
        ? (canvas ?? payloadSize)
        : null;
    }
    if (at + 8 > end) return null;
    const length = u32le(data, at + 4);
    if (length === null || at + 8 + length > end) return null;
    if (
      bytesEqual(data, at, [0x41, 0x4e, 0x49, 0x4d]) ||
      bytesEqual(data, at, [0x41, 0x4e, 0x4d, 0x46])
    )
      return null;
    const candidate = webpPayloadSize(data, at, at + 8, length);
    if (candidate !== null) {
      if (candidate.format !== "webp") return null;
      if (bytesEqual(data, at, [0x56, 0x50, 0x38, 0x58])) {
        if (canvas !== null || at !== 12) return null;
        canvas = candidate;
      } else {
        if (canvas === null && at !== 12) return null;
        imagePayloads += 1;
        if (imagePayloads > 1) return null;
        payloadSize = candidate;
      }
    } else if (
      bytesEqual(data, at, [0x56, 0x50, 0x38, 0x58]) ||
      bytesEqual(data, at, [0x56, 0x50, 0x38, 0x20]) ||
      bytesEqual(data, at, [0x56, 0x50, 0x38, 0x4c])
    ) {
      return null;
    }
    at += 8 + length + (length & 1);
  }
  return null;
}

function rawImageSize(data: Uint8Array): RawImageSize | null {
  if (bytesEqual(data, 0, [0x89, 0x50, 0x4e, 0x47])) return pngSize(data);
  if (bytesEqual(data, 0, [0x47, 0x49, 0x46, 0x38])) return gifSize(data);
  if (bytesEqual(data, 0, [0x52, 0x49, 0x46, 0x46])) return webpSize(data);
  return bytesEqual(data, 0, [0xff, 0xd8]) ? jpegSize(data) : null;
}

/** Validate encoded bytes before any browser image decoder sees them. */
export function inspectEncodedImage(
  data: Uint8Array,
  expectedMimeType?: string,
): ImageAdmission {
  return admitRawImage(rawImageSize(data), expectedMimeType);
}

function admitRawImage(
  raw: RawImageSize | null,
  expectedMimeType?: string,
): ImageAdmission {
  if (raw === null) return { ok: false, reason: MALFORMED_IMAGE_MESSAGE };
  const mimeType = MIME_FROM_FORMAT[raw.format];
  if (
    expectedMimeType !== undefined &&
    normalizedSafeRasterMimeType(expectedMimeType) !== mimeType
  ) {
    return { ok: false, reason: MALFORMED_IMAGE_MESSAGE };
  }
  if (raw.width > MAX_IMAGE_DIMENSION || raw.height > MAX_IMAGE_DIMENSION) {
    return {
      ok: false,
      reason: `Image preview is limited to ${MAX_IMAGE_DIMENSION.toLocaleString("en-US")} pixels per side.`,
    };
  }
  if (raw.width > Math.floor(MAX_IMAGE_PIXELS / raw.height)) {
    return {
      ok: false,
      reason: `Image preview is limited to ${MAX_IMAGE_PIXELS.toLocaleString("en-US")} decoded pixels.`,
    };
  }
  return {
    ok: true,
    format: raw.format,
    mimeType,
    size: { width: raw.width, height: raw.height },
  };
}

function decodeBase64(encoded: string): Uint8Array | null {
  if (encoded.length % 4 === 1 || !/^[A-Za-z0-9+/]*={0,2}$/.test(encoded))
    return null;
  try {
    const binary = globalThis.atob(encoded);
    const data = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      data[index] = binary.charCodeAt(index);
    }
    return data;
  } catch {
    return null;
  }
}

function decodePercentBytes(encoded: string): Uint8Array | null {
  const bytes: number[] = [];
  for (let index = 0; index < encoded.length; index += 1) {
    const code = encoded.charCodeAt(index);
    if (code === 0x25) {
      if (index + 2 >= encoded.length) return null;
      const pair = encoded.slice(index + 1, index + 3);
      if (!/^[0-9A-Fa-f]{2}$/.test(pair)) return null;
      const value = Number.parseInt(pair, 16);
      bytes.push(value);
      index += 2;
    } else {
      if (code > 0x7f) return null;
      bytes.push(code);
    }
  }
  return Uint8Array.from(bytes);
}

/** Inspect a bounded Markdown data image without putting it in an `<img>`. */
export function inspectImageDataUrl(src: string): ImageAdmission {
  if (
    !src.startsWith("data:") ||
    src.length > MAX_MARKDOWN_DATA_IMAGE_CODE_UNITS
  ) {
    return { ok: false, reason: MALFORMED_IMAGE_MESSAGE };
  }
  const comma = src.indexOf(",");
  if (comma < 5) return { ok: false, reason: MALFORMED_IMAGE_MESSAGE };
  const metadata = src.slice(5, comma).split(";");
  const mimeType = normalizedSafeRasterMimeType(metadata.shift() ?? "");
  if (mimeType === null) return { ok: false, reason: MALFORMED_IMAGE_MESSAGE };
  const base64 = metadata.at(-1)?.toLowerCase() === "base64";
  if (
    metadata.some(
      (part, index) =>
        part.toLowerCase() === "base64" && index !== metadata.length - 1,
    )
  ) {
    return { ok: false, reason: MALFORMED_IMAGE_MESSAGE };
  }
  const encoded = src.slice(comma + 1);
  const data = base64 ? decodeBase64(encoded) : decodePercentBytes(encoded);
  return data === null
    ? { ok: false, reason: MALFORMED_IMAGE_MESSAGE }
    : inspectEncodedImage(data, mimeType);
}

const BLOB_READ_CHUNK_BYTES = 64 * 1024;

/** Small random-access reader. Large IDAT/JPEG metadata/media chunks are
 * skipped by their declared lengths, so validating a 64 MiB file retains at
 * most one 64 KiB buffer rather than materializing a second copy of it. */
class BlobByteReader {
  private start = -1;
  private data = new Uint8Array();

  constructor(readonly blob: Blob) {}

  async bytes(at: number, length: number): Promise<Uint8Array | null> {
    if (
      !Number.isSafeInteger(at) ||
      !Number.isSafeInteger(length) ||
      at < 0 ||
      length < 0 ||
      at > this.blob.size - length
    )
      return null;
    if (at >= this.start && at + length <= this.start + this.data.length) {
      return this.data.subarray(at - this.start, at - this.start + length);
    }
    const end = Math.min(
      this.blob.size,
      at + Math.max(length, BLOB_READ_CHUNK_BYTES),
    );
    this.start = at;
    this.data = new Uint8Array(await this.blob.slice(at, end).arrayBuffer());
    return length <= this.data.length ? this.data.subarray(0, length) : null;
  }
}

function bytesText(data: Uint8Array, at = 0, length = data.length): string {
  let value = "";
  for (let index = 0; index < length; index += 1) {
    value += String.fromCharCode(data[at + index]);
  }
  return value;
}

async function blobJpegSize(
  reader: BlobByteReader,
): Promise<RawImageSize | null> {
  let at = 2;
  for (let item = 0; item < MAX_IMAGE_STRUCTURE_ITEMS; item += 1) {
    if (at + 4 > MAX_IMAGE_HEADER_BYTES) return null;
    const markerBytes = await reader.bytes(at, 4);
    if (markerBytes === null || markerBytes[0] !== 0xff) return null;
    const marker = markerBytes[1];
    at += 2;
    if (marker === 0xff) {
      at -= 1;
      continue;
    }
    if (
      marker === 0x01 ||
      marker === 0xd8 ||
      marker === 0xd9 ||
      (marker >= 0xd0 && marker <= 0xd7)
    )
      continue;
    if (marker === 0xda) return null;
    const length = markerBytes[2] * 256 + markerBytes[3];
    if (
      length < 2 ||
      at > reader.blob.size - length ||
      at > MAX_IMAGE_HEADER_BYTES - length
    )
      return null;
    if (JPEG_FRAME_MARKERS.has(marker)) {
      const frame = await reader.bytes(at, 8);
      if (frame === null) return null;
      const componentCount = frame[7];
      if (
        length < 11 ||
        componentCount === 0 ||
        length !== 8 + 3 * componentCount
      )
        return null;
      const height = frame[3] * 256 + frame[4];
      const width = frame[5] * 256 + frame[6];
      return width === 0 || height === 0
        ? null
        : { format: "jpeg", width, height };
    }
    at += length;
  }
  return null;
}

async function blobPngSize(
  reader: BlobByteReader,
): Promise<RawImageSize | null> {
  const signature = await reader.bytes(0, 8);
  if (
    signature === null ||
    !bytesEqual(signature, 0, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
  )
    return null;
  let at = 8;
  let size: RawImageSize | null = null;
  let hasImageData = false;
  for (let count = 0; count < MAX_IMAGE_STRUCTURE_ITEMS; count += 1) {
    const header = await reader.bytes(at, 8);
    if (header === null) return null;
    const length = u32be(header, 0);
    if (length === null || at > reader.blob.size - length - 12) return null;
    const type = bytesText(header, 4, 4);
    if (type === "acTL" || type === "fcTL" || type === "fdAT") return null;
    if (type === "IHDR") {
      if (at !== 8 || length !== 13 || size !== null) return null;
      const dimensions = await reader.bytes(at + 8, 8);
      if (dimensions === null) return null;
      const width = u32be(dimensions, 0);
      const height = u32be(dimensions, 4);
      if (width === null || height === null || width === 0 || height === 0)
        return null;
      size = { format: "png", width, height };
    }
    if (type === "IDAT") hasImageData = true;
    at += length + 12;
    if (type === "IEND")
      return length === 0 &&
        at === reader.blob.size &&
        size !== null &&
        hasImageData
        ? size
        : null;
  }
  return null;
}

interface StructureCounter {
  items: number;
}

async function skipBlobGifSubBlocks(
  reader: BlobByteReader,
  start: number,
  counter: StructureCounter,
): Promise<number | null> {
  let at = start;
  while (counter.items < MAX_IMAGE_STRUCTURE_ITEMS) {
    counter.items += 1;
    const lengthByte = await reader.bytes(at, 1);
    if (lengthByte === null) return null;
    at += 1;
    if (lengthByte[0] === 0) return at;
    if (at > reader.blob.size - lengthByte[0]) return null;
    at += lengthByte[0];
  }
  return null;
}

async function blobGifSize(
  reader: BlobByteReader,
): Promise<RawImageSize | null> {
  const header = await reader.bytes(0, 13);
  if (
    header === null ||
    (bytesText(header, 0, 6) !== "GIF87a" &&
      bytesText(header, 0, 6) !== "GIF89a")
  )
    return null;
  const width = u16le(header, 6);
  const height = u16le(header, 8);
  if (width === null || height === null || width === 0 || height === 0)
    return null;
  let at = 13;
  if ((header[10] & 0x80) !== 0) at += 3 * 2 ** ((header[10] & 7) + 1);
  let frameCount = 0;
  const counter = { items: 0 };
  while (counter.items < MAX_IMAGE_STRUCTURE_ITEMS) {
    counter.items += 1;
    const introducerBytes = await reader.bytes(at, 1);
    if (introducerBytes === null) return null;
    const introducer = introducerBytes[0];
    at += 1;
    if (introducer === 0x3b)
      return frameCount === 1 && at === reader.blob.size
        ? { format: "gif", width, height }
        : null;
    if (introducer === 0x21) {
      if ((await reader.bytes(at, 1)) === null) return null;
      const next = await skipBlobGifSubBlocks(reader, at + 1, counter);
      if (next === null) return null;
      at = next;
      continue;
    }
    if (introducer !== 0x2c) return null;
    const descriptor = await reader.bytes(at, 9);
    if (descriptor === null) return null;
    frameCount += 1;
    if (frameCount > 1) return null;
    const left = u16le(descriptor, 0)!;
    const top = u16le(descriptor, 2)!;
    const frameWidth = u16le(descriptor, 4)!;
    const frameHeight = u16le(descriptor, 6)!;
    if (
      frameWidth === 0 ||
      frameHeight === 0 ||
      left + frameWidth > width ||
      top + frameHeight > height
    )
      return null;
    at += 9;
    if ((descriptor[8] & 0x80) !== 0) at += 3 * 2 ** ((descriptor[8] & 7) + 1);
    if ((await reader.bytes(at, 1)) === null) return null;
    const next = await skipBlobGifSubBlocks(reader, at + 1, counter);
    if (next === null) return null;
    at = next;
  }
  return null;
}

async function blobWebpSize(
  reader: BlobByteReader,
): Promise<RawImageSize | null> {
  const header = await reader.bytes(0, 12);
  if (
    header === null ||
    bytesText(header, 0, 4) !== "RIFF" ||
    bytesText(header, 8, 4) !== "WEBP"
  )
    return null;
  const riffSize = u32le(header, 4);
  if (riffSize === null || riffSize < 4 || riffSize + 8 !== reader.blob.size)
    return null;
  const end = riffSize + 8;
  let at = 12;
  let canvas: RawImageSize | null = null;
  let payloadSize: RawImageSize | null = null;
  let payloads = 0;
  for (let count = 0; count < MAX_IMAGE_STRUCTURE_ITEMS; count += 1) {
    if (at === end) {
      if (payloadSize === null || payloads !== 1) return null;
      return canvas === null ||
        (canvas.width === payloadSize.width &&
          canvas.height === payloadSize.height)
        ? (canvas ?? payloadSize)
        : null;
    }
    const chunk = await reader.bytes(at, 8);
    if (chunk === null) return null;
    const type = bytesText(chunk, 0, 4);
    const length = u32le(chunk, 4);
    if (length === null || at > end - length - 8) return null;
    if (type === "ANIM" || type === "ANMF") return null;
    let candidate: RawImageSize | null = null;
    if (type === "VP8X") {
      const payload = await reader.bytes(at + 8, 10);
      if (
        length !== 10 ||
        payload === null ||
        (payload[0] & 0x02) !== 0 ||
        at !== 12
      )
        return null;
      const width = u24le(payload, 4);
      const height = u24le(payload, 7);
      if (width === null || height === null || canvas !== null) return null;
      candidate = { format: "webp", width: width + 1, height: height + 1 };
    } else if (type === "VP8 ") {
      if (canvas === null && at !== 12) return null;
      const payload = await reader.bytes(at + 8, 10);
      if (
        length < 10 ||
        payload === null ||
        !bytesEqual(payload, 3, [0x9d, 0x01, 0x2a])
      )
        return null;
      const rawWidth = u16le(payload, 6);
      const rawHeight = u16le(payload, 8);
      const width = rawWidth === null ? 0 : rawWidth & 0x3fff;
      const height = rawHeight === null ? 0 : rawHeight & 0x3fff;
      if (width === 0 || height === 0) return null;
      candidate = { format: "webp", width, height };
      payloads += 1;
    } else if (type === "VP8L") {
      if (canvas === null && at !== 12) return null;
      const payload = await reader.bytes(at + 8, 5);
      if (length < 5 || payload === null || payload[0] !== 0x2f) return null;
      const packed = u32le(payload, 1)!;
      candidate = {
        format: "webp",
        width: (packed & 0x3fff) + 1,
        height: ((packed >>> 14) & 0x3fff) + 1,
      };
      payloads += 1;
    }
    if (candidate !== null) {
      if (payloads > 1) return null;
      if (type === "VP8X") canvas = candidate;
      else payloadSize = candidate;
    }
    at += 8 + length + (length & 1);
  }
  return null;
}

export async function inspectImageBlob(
  blob: Blob,
  mimeType: string,
): Promise<ImageAdmission> {
  try {
    if (!Number.isSafeInteger(blob.size) || blob.size <= 0)
      return { ok: false, reason: MALFORMED_IMAGE_MESSAGE };
    const reader = new BlobByteReader(blob);
    const signature = await reader.bytes(0, Math.min(12, blob.size));
    if (signature === null)
      return { ok: false, reason: MALFORMED_IMAGE_MESSAGE };
    let raw: RawImageSize | null;
    if (bytesEqual(signature, 0, [0x89, 0x50, 0x4e, 0x47]))
      raw = await blobPngSize(reader);
    else if (bytesEqual(signature, 0, [0x47, 0x49, 0x46, 0x38]))
      raw = await blobGifSize(reader);
    else if (bytesEqual(signature, 0, [0x52, 0x49, 0x46, 0x46]))
      raw = await blobWebpSize(reader);
    else if (bytesEqual(signature, 0, [0xff, 0xd8]))
      raw = await blobJpegSize(reader);
    else raw = null;
    return admitRawImage(raw, mimeType);
  } catch {
    return { ok: false, reason: MALFORMED_IMAGE_MESSAGE };
  }
}

type ImageResult = (result: ImageAdmission) => void;
interface ImageRequest {
  blob: Blob;
  mimeType: string;
  result: ImageResult | null;
}

/** Serialize file-header reads, retaining only the active and newest Blob. */
export class LatestBlobImageInspector {
  private active: ImageRequest | null = null;
  private pending: ImageRequest | null = null;

  request(blob: Blob, mimeType: string, result: ImageResult): () => void {
    if (this.active?.blob === blob && this.active.mimeType === mimeType) {
      const active = this.active;
      active.result = result;
      if (this.pending !== null) this.pending.result = null;
      this.pending = null;
      return () => {
        if (active.result === result) active.result = null;
      };
    }
    const request: ImageRequest = { blob, mimeType, result };
    if (this.active === null) this.start(request);
    else {
      this.active.result = null;
      if (this.pending !== null) this.pending.result = null;
      this.pending = request;
    }
    return () => {
      request.result = null;
      if (this.pending === request) this.pending = null;
    };
  }

  clear(): void {
    if (this.active !== null) this.active.result = null;
    if (this.pending !== null) this.pending.result = null;
    this.pending = null;
  }

  private start(request: ImageRequest): void {
    this.active = request;
    void inspectImageBlob(request.blob, request.mimeType).then((admission) => {
      const result = request.result;
      request.result = null;
      try {
        result?.(admission);
      } finally {
        if (this.active === request) this.active = null;
        const next = this.pending;
        this.pending = null;
        if (next !== null && next.result !== null) this.start(next);
      }
    });
  }
}
