import type {
  FileTransferAbort,
  FileTransferPartAck,
} from "./WebsocketMessages";

export const FILE_UPLOAD_ACK_TIMEOUT_MS = 30_000;
/** Match the server's page/session upload admission limit so a burst of
 * controls cannot retain unbounded Files, send closures, and ACK timers while
 * waiting for the server to reject them. */
export const FILE_UPLOAD_MAX_ACTIVE = 128;
const FILE_UPLOAD_ABORT_REASON_MAX_LENGTH = 160;
const CONTROL_OR_FORMAT = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}]/u;

/** A controlled upload failure, including whether the client should ask the
 * server to release the transfer reservation it has already accepted. */
export class FileUploadError extends Error {
  constructor(
    message: string,
    readonly notifyServer: boolean,
    readonly visible = true,
  ) {
    super(message);
    this.name = "FileUploadError";
  }
}

type AckWaiter = {
  expectedBytes: number;
  timeout: ReturnType<typeof globalThis.setTimeout>;
  resolve: () => void;
  reject: (error: FileUploadError) => void;
};

type UploadState = {
  transferUuid: string;
  componentUuid: string;
  totalBytes: number;
  waiter: AckWaiter | null;
  failure: FileUploadError | null;
};

export type FileUploadAckAcceptance =
  | { matched: false }
  | {
      matched: true;
      accepted: boolean;
      componentUuid: string;
    };

export type FileUploadAbortAcceptance =
  { matched: false } | { matched: true; componentUuid: string };

/** The sending half of one broker registration. */
export interface FileUploadAcknowledgements {
  waitForAck(expectedBytes: number, timeoutMs?: number): Promise<void>;
  cancel(error: FileUploadError): void;
  complete(): void;
  finish(): void;
}

/** Route server acknowledgements to exactly one active upload.
 *
 * A sender installs its waiter before putting the corresponding start/part on
 * the socket. Therefore an ACK with no waiter, the wrong cumulative byte
 * count, component, or total is a protocol error rather than something to
 * buffer and reinterpret later. */
export class FileUploadAckBroker {
  private readonly uploads = new Map<string, UploadState>();

  begin(
    transferUuid: string,
    componentUuid: string,
    totalBytes: number,
  ): FileUploadAcknowledgements {
    if (this.uploads.has(transferUuid)) {
      throw new FileUploadError(
        "An upload with this transfer ID is already active.",
        false,
      );
    }
    if (this.uploads.size >= FILE_UPLOAD_MAX_ACTIVE) {
      throw new FileUploadError(
        "Too many uploads are already active in this browser tab.",
        false,
      );
    }
    if (
      [...this.uploads.values()].some(
        (upload) => upload.componentUuid === componentUuid,
      )
    ) {
      throw new FileUploadError(
        "Another upload is already active for this control.",
        false,
      );
    }

    const state: UploadState = {
      transferUuid,
      componentUuid,
      totalBytes,
      waiter: null,
      failure: null,
    };
    this.uploads.set(transferUuid, state);
    return {
      waitForAck: (expectedBytes, timeoutMs = FILE_UPLOAD_ACK_TIMEOUT_MS) =>
        this.waitForAck(state, expectedBytes, timeoutMs),
      cancel: (error) => this.reject(state, error),
      complete: () => this.complete(state),
      finish: () => this.finish(state),
    };
  }

  acceptAck(message: FileTransferPartAck): FileUploadAckAcceptance {
    const state = this.uploads.get(message.transfer_uuid);
    if (state === undefined) return { matched: false };

    const waiter = state.waiter;
    const validEnvelope =
      message.source_component_uuid === state.componentUuid &&
      Number.isSafeInteger(message.transferred_bytes) &&
      message.transferred_bytes >= 0 &&
      Number.isSafeInteger(message.total_bytes) &&
      message.total_bytes === state.totalBytes;
    if (
      !validEnvelope ||
      waiter === null ||
      message.transferred_bytes !== waiter.expectedBytes
    ) {
      this.reject(
        state,
        new FileUploadError(
          "The server sent an invalid upload acknowledgement.",
          true,
        ),
      );
      return {
        matched: true,
        accepted: false,
        componentUuid: state.componentUuid,
      };
    }

    state.waiter = null;
    globalThis.clearTimeout(waiter.timeout);
    waiter.resolve();
    return {
      matched: true,
      accepted: true,
      componentUuid: state.componentUuid,
    };
  }

  /** Consume a server abort only when it names an active upload. The caller
   * can otherwise offer the same bidirectional message to download assembly. */
  acceptAbort(message: FileTransferAbort): FileUploadAbortAcceptance {
    const state = this.uploads.get(message.transfer_uuid);
    if (state === undefined) return { matched: false };
    const validReason =
      typeof message.reason === "string" &&
      message.reason.length <= FILE_UPLOAD_ABORT_REASON_MAX_LENGTH &&
      !CONTROL_OR_FORMAT.test(message.reason);
    const reason = validReason
      ? message.reason.trim()
      : "The server sent an invalid upload rejection.";
    this.reject(
      state,
      new FileUploadError(
        reason === "" ? "The server stopped the upload." : reason,
        false,
      ),
    );
    return { matched: true, componentUuid: state.componentUuid };
  }

  /** End every promise owned by the connection that is being replaced. */
  reset(reason = "The connection changed during the upload."): void {
    for (const state of [...this.uploads.values()]) {
      this.reject(state, new FileUploadError(reason, false));
    }
  }

  private waitForAck(
    state: UploadState,
    expectedBytes: number,
    timeoutMs: number,
  ): Promise<void> {
    if (this.uploads.get(state.transferUuid) !== state) {
      throw (
        state.failure ??
        new FileUploadError("The upload is no longer active.", false)
      );
    }
    if (
      state.waiter !== null ||
      !Number.isSafeInteger(expectedBytes) ||
      expectedBytes < 0 ||
      expectedBytes > state.totalBytes ||
      !Number.isFinite(timeoutMs) ||
      timeoutMs < 0
    ) {
      const error = new FileUploadError(
        "The client could not sequence the upload.",
        true,
      );
      this.reject(state, error);
      throw error;
    }

    return new Promise<void>((resolve, reject) => {
      const timeout = globalThis.setTimeout(() => {
        this.reject(
          state,
          new FileUploadError(
            "The server did not acknowledge the upload.",
            true,
          ),
        );
      }, timeoutMs);
      state.waiter = { expectedBytes, timeout, resolve, reject };
    });
  }

  private reject(state: UploadState, error: FileUploadError): void {
    if (this.uploads.get(state.transferUuid) !== state) return;
    this.uploads.delete(state.transferUuid);
    state.failure = error;
    const waiter = state.waiter;
    state.waiter = null;
    if (waiter === null) return;
    globalThis.clearTimeout(waiter.timeout);
    waiter.reject(error);
  }

  /** Commit a fully acknowledged sender. This runs inside the sender's try
   * block, so an abort or invalid duplicate ACK delivered in the same batch as
   * the final ACK is still surfaced and answered with a client abort. */
  private complete(state: UploadState): void {
    if (this.uploads.get(state.transferUuid) !== state) {
      throw (
        state.failure ??
        new FileUploadError("The upload is no longer active.", false)
      );
    }
    if (state.waiter !== null) {
      const error = new FileUploadError(
        "The upload ended before acknowledgement.",
        true,
      );
      this.reject(state, error);
      throw error;
    }
    this.uploads.delete(state.transferUuid);
  }

  private finish(state: UploadState): void {
    if (this.uploads.get(state.transferUuid) !== state) return;
    this.uploads.delete(state.transferUuid);
    const waiter = state.waiter;
    state.waiter = null;
    if (waiter === null) return;
    globalThis.clearTimeout(waiter.timeout);
    waiter.reject(
      new FileUploadError("The upload ended before acknowledgement.", true),
    );
  }
}
