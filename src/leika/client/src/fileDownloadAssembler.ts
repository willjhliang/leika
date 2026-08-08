import {
  FileTransferAbort,
  FileTransferPart,
  FileTransferStartDownload,
} from "./WebsocketMessages";

export interface AssembledFileDownload {
  metadata: FileTransferStartDownload;
  parts: Uint8Array<ArrayBuffer>[];
}

export type FileDownloadAssemblyResult =
  | { status: "pending" }
  | ({ status: "complete" } & AssembledFileDownload)
  | {
      status: "rejected";
      reason: string;
      metadata: FileTransferStartDownload | null;
    };

type DownloadState = {
  metadata: FileTransferStartDownload;
  parts: Map<number, Uint8Array<ArrayBuffer>>;
  receivedBytes: number;
};

/** Assemble one connection's validated, chunked file downloads. */
export class FileDownloadAssembler {
  private readonly states = new Map<string, DownloadState>();

  /** Forget every partial transfer when its connection ends. */
  reset(): void {
    this.states.clear();
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
    const state = this.states.get(message.transfer_uuid);
    this.states.delete(message.transfer_uuid);
    return this.rejected(
      message.transfer_uuid,
      "server aborted the transfer: " + message.reason,
      state?.metadata ?? null,
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
    // A duplicate start is a protocol error. Abort the displaced transfer so
    // its preview/reload side effects can be unwound instead of silently
    // blending two transfers with the same ID.
    const displaced = this.states.get(id);
    this.states.delete(id);
    if (displaced !== undefined) {
      return this.rejected(
        id,
        "start arrived more than once",
        displaced.metadata,
      );
    }
    if (!Number.isSafeInteger(partCount) || partCount < 0) {
      return this.rejected(id, "invalid part count " + partCount);
    }
    if (!Number.isSafeInteger(sizeBytes) || sizeBytes < 0) {
      return this.rejected(id, "invalid byte size " + sizeBytes);
    }
    if (partCount === 0) {
      return sizeBytes === 0
        ? { status: "complete", metadata, parts: [] }
        : this.rejected(id, "declared bytes without any parts");
    }
    this.states.set(id, {
      metadata,
      parts: new Map(),
      receivedBytes: 0,
    });
    return { status: "pending" };
  }

  private addPart(part: FileTransferPart): FileDownloadAssemblyResult {
    const id = part.transfer_uuid;
    const state = this.states.get(id);
    if (state === undefined) {
      return this.rejected(id, "part arrived without a transfer start");
    }
    const index = part.part_index;
    if (
      !Number.isSafeInteger(index) ||
      index < 0 ||
      index >= state.metadata.part_count
    ) {
      this.states.delete(id);
      return this.rejected(
        id,
        "part index " + index + " is out of range",
        state.metadata,
      );
    }
    if (state.parts.has(index)) {
      this.states.delete(id);
      return this.rejected(
        id,
        "part index " + index + " arrived more than once",
        state.metadata,
      );
    }

    state.parts.set(index, part.content);
    state.receivedBytes += part.content.byteLength;
    if (state.receivedBytes > state.metadata.size_bytes) {
      this.states.delete(id);
      return this.rejected(
        id,
        "parts exceed the declared byte size",
        state.metadata,
      );
    }
    if (state.parts.size < state.metadata.part_count) {
      return { status: "pending" };
    }

    this.states.delete(id);
    if (state.receivedBytes !== state.metadata.size_bytes) {
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
    const parts: Uint8Array<ArrayBuffer>[] = [];
    for (let index = 0; index < state.metadata.part_count; index += 1) {
      // Size equality and the part-count check above guarantee every index.
      parts.push(state.parts.get(index)!);
    }
    return { status: "complete", metadata: state.metadata, parts };
  }

  private rejected(
    id: string,
    detail: string,
    metadata: FileTransferStartDownload | null = null,
  ): FileDownloadAssemblyResult {
    return {
      status: "rejected",
      reason: "Rejected file transfer " + id + ": " + detail + ".",
      metadata,
    };
  }
}
