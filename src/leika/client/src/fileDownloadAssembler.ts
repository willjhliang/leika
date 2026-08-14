import {
  validFileTransferFilename,
  validFileTransferIdentifier,
  validFileTransferMimeType,
} from "./fileTransferValidation";
import {
  FILE_DOWNLOAD_MEMORY_MAX_BYTES,
  RETAINED_DOWNLOAD_PRIORITY,
  type DownloadMemoryReservation,
  RetainedDownloadBudget,
  type RetainedDownloadPriority,
} from "./retainedDownloadBudget";
import {
  FileTransferAbort,
  FileTransferPart,
  FileTransferStartDownload,
} from "./WebsocketMessages";

export interface AssembledFileDownload {
  metadata: FileTransferStartDownload;
  parts: Uint8Array<ArrayBuffer>[];
  reservation: DownloadMemoryReservation;
}

export type FileDownloadAssemblyResult =
  | { status: "pending" }
  | { status: "ignored" }
  | ({ status: "complete" } & AssembledFileDownload)
  | {
      status: "rejected";
      reason: string;
      metadata: FileTransferStartDownload | null;
      /** One bounded cancellation for a locally rejected, valid transfer. */
      peerAbort: FileTransferAbort | null;
    };

type DownloadState = {
  metadata: FileTransferStartDownload;
  parts: Map<number, Uint8Array<ArrayBuffer>>;
  receivedBytes: number;
  reservation: DownloadMemoryReservation;
};

const FILE_DISPOSITIONS = new Set([
  "save",
  "link",
  "preview",
  "warm",
  "reload",
]);
const MAX_METADATA_TEXT_LENGTH = 16_384;

/** Maximum declared size of one browser-assembled download. */
export const FILE_DOWNLOAD_MAX_BYTES = 256 * 1024 * 1024;
/** Active and completed browser file bytes share one aggregate budget. */
export const FILE_DOWNLOAD_AGGREGATE_MAX_BYTES = FILE_DOWNLOAD_MEMORY_MAX_BYTES;
/** Maximum number of simultaneously active browser download assemblies. */
export const FILE_DOWNLOAD_MAX_ACTIVE = 128;
/** Maximum number of retained chunks in one browser download assembly. */
export const FILE_DOWNLOAD_MAX_PARTS = 65_536;
/** Maximum received part objects retained across every active assembly. */
export const FILE_DOWNLOAD_AGGREGATE_MAX_RECEIVED_PARTS = 65_536;
/** Rejected IDs remembered while their server cancellation is in flight. */
export const FILE_DOWNLOAD_MAX_REJECTED_IDS = 512;

const BROWSER_REJECTION_REASON = "Browser rejected the file transfer.";

function dispositionPriority(
  disposition: FileTransferStartDownload["disposition"],
): RetainedDownloadPriority {
  if (disposition === "warm") return RETAINED_DOWNLOAD_PRIORITY.warm;
  if (disposition === "link") return RETAINED_DOWNLOAD_PRIORITY.link;
  if (disposition === "save") return RETAINED_DOWNLOAD_PRIORITY.save;
  return RETAINED_DOWNLOAD_PRIORITY.preview;
}

/** Assemble one connection's validated, chunked file downloads. */
export class FileDownloadAssembler {
  private readonly states = new Map<string, DownloadState>();
  private readonly rejectedIds = new Set<string>();
  private receivedPartCountValue = 0;

  constructor(private readonly memoryBudget = new RetainedDownloadBudget()) {}

  /** Exposed for connection diagnostics and exact accounting regressions. */
  get receivedPartCount(): number {
    return this.receivedPartCountValue;
  }

  /** Forget every partial transfer when its connection ends. */
  reset(): void {
    for (const state of this.states.values()) state.reservation.release();
    this.states.clear();
    this.rejectedIds.clear();
    this.receivedPartCountValue = 0;
  }

  accept(
    message: FileTransferStartDownload | FileTransferPart | FileTransferAbort,
  ): FileDownloadAssemblyResult {
    if (message.type === "FileTransferStartDownload") {
      return this.start(message);
    }
    if (message.type === "FileTransferAbort") {
      return this.abort(message);
    }
    return this.addPart(message);
  }

  private abort(message: FileTransferAbort): FileDownloadAssemblyResult {
    const id = message.transfer_uuid;
    if (!validFileTransferIdentifier(id)) {
      return this.rejected(
        "unknown",
        "abort has an invalid transfer ID",
        null,
        false,
      );
    }
    // The peer has acknowledged cancellation. Do not log every ordinary
    // terminal Abort for a transfer we already rejected, and never echo it.
    if (this.rejectedIds.delete(id)) return { status: "ignored" };
    const state = this.removeState(id);
    if (
      typeof message.reason !== "string" ||
      message.reason.length > MAX_METADATA_TEXT_LENGTH
    ) {
      return this.rejected(
        id,
        "abort has an invalid reason",
        state?.metadata ?? null,
        false,
      );
    }
    return this.rejected(
      id,
      "server aborted the transfer: " + message.reason,
      state?.metadata ?? null,
      false,
    );
  }

  private start(
    metadata: FileTransferStartDownload,
  ): FileDownloadAssemblyResult {
    const {
      transfer_uuid: id,
      part_count: partCount,
      size_bytes: sizeBytes,
    } = metadata;
    if (!validFileTransferIdentifier(id)) {
      return this.rejected(
        "unknown",
        "start has an invalid transfer ID",
        null,
        false,
      );
    }
    // A fresh Start is allowed to reuse an ID whose prior transfer was
    // cancelled. It begins a new rejection/cancellation lifecycle.
    this.rejectedIds.delete(id);
    // A duplicate start is a protocol error. Abort the displaced transfer so
    // its preview/reload side effects can be unwound instead of silently
    // blending two transfers with the same ID.
    const displaced = this.removeState(id);
    if (displaced !== undefined) {
      return this.rejected(
        id,
        "start arrived more than once",
        displaced.metadata,
      );
    }
    if (
      !FILE_DISPOSITIONS.has(metadata.disposition) ||
      !validFileTransferFilename(metadata.filename) ||
      !validFileTransferMimeType(metadata.mime_type) ||
      !(
        metadata.source_uuid === null ||
        validFileTransferIdentifier(metadata.source_uuid)
      ) ||
      !(
        metadata.source_version === null ||
        (typeof metadata.source_version === "string" &&
          metadata.source_version.length <= MAX_METADATA_TEXT_LENGTH)
      )
    ) {
      return this.rejected(id, "invalid transfer metadata");
    }
    if (!Number.isSafeInteger(partCount) || partCount < 0) {
      return this.rejected(id, "invalid part count " + partCount);
    }
    if (!Number.isSafeInteger(sizeBytes) || sizeBytes < 0) {
      return this.rejected(id, "invalid byte size " + sizeBytes);
    }
    if ((partCount === 0) !== (sizeBytes === 0)) {
      return this.rejected(id, "empty transfer metadata is inconsistent");
    }
    if (partCount > sizeBytes) {
      return this.rejected(id, "part count exceeds the declared byte size");
    }
    if (partCount > FILE_DOWNLOAD_MAX_PARTS) {
      return this.rejected(id, "part count exceeds the 65,536 browser limit");
    }
    if (sizeBytes > FILE_DOWNLOAD_MAX_BYTES) {
      return this.rejected(
        id,
        "declared byte size exceeds the 256 MiB browser limit",
      );
    }
    if (partCount !== 0 && this.states.size >= FILE_DOWNLOAD_MAX_ACTIVE) {
      return this.rejected(
        id,
        "too many browser downloads are already being assembled",
      );
    }
    const reservation = this.memoryBudget.reserve(sizeBytes, {
      priority: dispositionPriority(metadata.disposition),
    });
    if (reservation === null) {
      return this.rejected(
        id,
        "active and completed files exceed the 512 MiB browser memory limit",
      );
    }
    if (partCount === 0) {
      return { status: "complete", metadata, parts: [], reservation };
    }
    this.states.set(id, {
      metadata,
      parts: new Map(),
      receivedBytes: 0,
      reservation,
    });
    return { status: "pending" };
  }

  private addPart(part: FileTransferPart): FileDownloadAssemblyResult {
    const id = part.transfer_uuid;
    if (!validFileTransferIdentifier(id)) {
      return this.rejected(
        "unknown",
        "part has an invalid transfer ID",
        null,
        false,
      );
    }
    if (this.rejectedIds.has(id)) return { status: "ignored" };
    const state = this.states.get(id);
    if (state === undefined) {
      return this.rejected(id, "part arrived without a transfer start");
    }
    if (
      part.source_component_uuid !== null ||
      !(part.content instanceof Uint8Array) ||
      !(part.content.buffer instanceof ArrayBuffer) ||
      part.content.byteLength === 0
    ) {
      this.removeState(id);
      return this.rejected(id, "part content is invalid", state.metadata);
    }
    if (
      part.content.byteLength >
      state.metadata.size_bytes - state.receivedBytes
    ) {
      this.removeState(id);
      return this.rejected(
        id,
        "parts exceed the declared byte size",
        state.metadata,
      );
    }
    const index = part.part_index;
    if (
      !Number.isSafeInteger(index) ||
      index < 0 ||
      index >= state.metadata.part_count
    ) {
      this.removeState(id);
      return this.rejected(
        id,
        "part index " + index + " is out of range",
        state.metadata,
      );
    }
    if (state.parts.has(index)) {
      this.removeState(id);
      return this.rejected(
        id,
        "part index " + index + " arrived more than once",
        state.metadata,
      );
    }
    if (
      this.receivedPartCountValue >= FILE_DOWNLOAD_AGGREGATE_MAX_RECEIVED_PARTS
    ) {
      this.removeState(id);
      return this.rejected(
        id,
        "received parts exceed the aggregate 65,536 browser limit",
        state.metadata,
      );
    }

    // A decoded byte view can cover only a few bytes of a much larger zstd
    // metadata buffer. Copy the exact part before retaining it so one tiny
    // chunk cannot pin an entire WebSocket frame outside our byte accounting.
    const content = new Uint8Array(part.content);
    state.parts.set(index, content);
    this.receivedPartCountValue += 1;
    state.receivedBytes += content.byteLength;
    if (state.parts.size < state.metadata.part_count) {
      return { status: "pending" };
    }

    if (state.receivedBytes !== state.metadata.size_bytes) {
      this.removeState(id);
      return this.rejected(
        id,
        "parts contain " +
          state.receivedBytes +
          " of " +
          state.metadata.size_bytes +
          " declared bytes",
        state.metadata,
      );
    }
    this.removeState(id, false);
    const parts: Uint8Array<ArrayBuffer>[] = [];
    for (let index = 0; index < state.metadata.part_count; index += 1) {
      // Size equality and the part-count check above guarantee every index.
      parts.push(state.parts.get(index)!);
    }
    return {
      status: "complete",
      metadata: state.metadata,
      parts,
      reservation: state.reservation,
    };
  }

  /** Remove a state, retaining its token only for atomic Blob ownership. */
  private removeState(
    id: string,
    releaseReservation = true,
  ): DownloadState | undefined {
    const state = this.states.get(id);
    if (state === undefined) return undefined;
    this.states.delete(id);
    this.receivedPartCountValue -= state.parts.size;
    if (releaseReservation) state.reservation.release();
    return state;
  }

  private rejected(
    id: string,
    detail: string,
    metadata: FileTransferStartDownload | null = null,
    notifyPeer = true,
  ): FileDownloadAssemblyResult {
    let peerAbort: FileTransferAbort | null = null;
    if (notifyPeer && validFileTransferIdentifier(id)) {
      if (!this.rejectedIds.has(id)) {
        this.rejectedIds.add(id);
        while (this.rejectedIds.size > FILE_DOWNLOAD_MAX_REJECTED_IDS) {
          this.rejectedIds.delete(this.rejectedIds.values().next().value!);
        }
        peerAbort = {
          type: "FileTransferAbort",
          transfer_uuid: id,
          reason: BROWSER_REJECTION_REASON,
        };
      }
    }
    return {
      status: "rejected",
      reason: "Rejected file transfer " + id + ": " + detail + ".",
      metadata,
      peerAbort,
    };
  }
}
